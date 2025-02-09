import requests
import json
import yaml
import qrcode
import os
import datetime
import time
import math
import pyaxie_utils

from datetime import timedelta, date
from web3 import Web3, exceptions
from web3.auto import w3
from eth_account.messages import encode_defunct
from pprint import pprint
from pycoingecko import CoinGeckoAPI

class pyaxie(object):

	def __init__(self, ronin_address="", private_key=""):
		"""
		Init the class variables, we need a ronin address and its private key
		:param ronin_address: The ronin address
		:param private_key: Private key belonging to the ronin account
		"""
		config_file = os.getenv("CONFIG_FILE", "secret.yaml")
		with open(config_file, "r") as file:
			config = yaml.safe_load(file)

		self.config = config
		self.ronin_address = ronin_address.replace('ronin:', '0x')
		self.private_key = private_key.replace('0x', '')
		self.headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36', 'authorization': ""}
		self.url = "https://axieinfinity.com/graphql-server-v2/graphql"
		self.url_api = config['url_api']
		# TODO: uncomment this to add ronin write access
		# should be optional if private key is not set
		# access tokens are good for a week, these should be cached
		self.access_token = self.get_access_token()
		self.account_id = 0
		self.email = ""
		self.slp_contract = None
		self.ronin_web3 = self.get_ronin_web3()
		self.axie_list_path = config['paths']['axie_list_path']
		self.slp_track_path = config['paths']['slp_track_path']
		self.slp_abi_path = 'slp_abi.json'
		self.axie_abi_path = 'slp_abi.json'
		self.slp_contract = self.get_slp_contract(self.ronin_web3, self.slp_abi_path)
		self.name = "you"

		for scholar in config['scholars']:
			if config['scholars'][scholar]['ronin_address'] == ronin_address:
				self.payout_percentage = config['scholars'][scholar]['payout_percentage']
				self.personal_ronin = config['scholars'][scholar]['personal_ronin'].replace('ronin:', '0x')
				self.name = scholar
				break
			else:
				self.payout_percentage = 0
				self.personal_ronin = None

	############################
	# Authentication functions #
	############################

	def get_raw_message(self):
		"""
		Ask the API for a message to sign with the private key (authenticate)
		:return: message to sign
		"""
		body = {"operationName": "CreateRandomMessage", "variables": {}, "query": "mutation CreateRandomMessage {\n  createRandomMessage\n}\n"}

		r = requests.post(self.url, headers=self.headers, data=body)
		try:
			json_data = json.loads(r.text)
		except ValueError as e:
			return e
		return json_data['data']['createRandomMessage']

	def sign_message(self, raw_message, private=''):
		"""
		Sign a raw message
		:param raw_message: The raw message from get_raw_message()
		:param private: The private key of the account
		:return: The signed message
		"""
		if not private:
			private = self.private_key
		pk = bytearray.fromhex(private)
		try:
			message = encode_defunct(text=raw_message)
			hex_signature = w3.eth.account.sign_message(message, private_key=pk)
			return hex_signature
		except 'JSONDecodeError' as e:
			return e + " | Maybe a problem with the axie request"

	def submit_signature(self, signed_message, raw_message, ronin_address=''):
		"""
		Function to submit the signature and get authorization
		:param signed_message: The signed message from sign_message()
		:param raw_message: The raw message from get_row_message()
		:param ronin_address: THe ronin address of the account
		:return: The access token
		"""
		if not ronin_address:
			ronin_address = self.ronin_address

		body = {"operationName": "CreateAccessTokenWithSignature", "variables": {"input": {"mainnet": "ronin", "owner": "User's Eth Wallet Address", "message": "User's Raw Message", "signature": "User's Signed Message"}}, "query": "mutation CreateAccessTokenWithSignature($input: SignatureInput!) {  createAccessTokenWithSignature(input: $input) {    newAccount    result    accessToken    __typename  }}"}
		body['variables']['input']['signature'] = signed_message['signature'].hex()
		body['variables']['input']['message'] = raw_message
		body['variables']['input']['owner'] = ronin_address
		r = requests.post(self.url, headers=self.headers, json=body)

		try:
			json_data = json.loads(r.text)
		except ValueError as e:
			return e
		return json_data['data']['createAccessTokenWithSignature']['accessToken']

	def get_access_token(self):
		"""
		Get an access token as proof of authentication
		:return: The access token in string
		"""
		if not self.private_key:
			return
		msg = self.get_raw_message()
		signed = self.sign_message(msg)
		if "JSONDecodeError" in signed:
			print("Error getting the signed message, trying again.")
			token = self.get_access_token()
		else:
			token = self.submit_signature(signed, msg)
		self.access_token = token
		self.headers['authorization'] = 'Bearer ' + token
		return token

	def get_qr_code(self):
		"""
		Function to create a QRCode from an access_token
		"""
		img = qrcode.make(self.access_token)
		name = 'QRCode-' + str(datetime.datetime.now()) + '.png'
		img.save(name)
		return name

	#################################
	# Account interaction functions #
	#################################

	def get_price(self, currency):
		"""
		Get the price in USD for 1 ETH / SLP / AXS
		:return: The price in US of 1 token
		"""
		body = {"operationName": "NewEthExchangeRate", "variables": {}, "query": "query NewEthExchangeRate {\n  exchangeRate {\n    " + currency.lower() + " {\n      usd\n      __typename\n    }\n    __typename\n  }\n}\n"}
		r = requests.post(self.url, headers=self.headers, json=body)
		try:
			json_data = json.loads(r.text)
		except ValueError as e:
			return e
		return json_data['data']['exchangeRate'][currency.lower()]['usd']

	def get_profile_data(self):
		"""
		Retrieve your profile/account data
		:return: Your profil data as dict
		"""
		body = {"operationName": "GetProfileBrief", "variables": {}, "query": "query GetProfileBrief {\n  profile {\n    ...ProfileBrief\n    __typename\n  }\n}\n\nfragment ProfileBrief on AccountProfile {\n  accountId\n  addresses {\n    ...Addresses\n    __typename\n  }\n  email\n  activated\n  name\n  settings {\n    unsubscribeNotificationEmail\n    __typename\n  }\n  __typename\n}\n\nfragment Addresses on NetAddresses {\n  ethereum\n  tomo\n  loom\n  ronin\n  __typename\n}\n"}
		r = requests.post(self.url, headers=self.headers, json=body)
		try:
			json_data = json.loads(r.text)
		except ValueError as e:
			return e['data']['profile']

		self.account_id = json_data['data']['profile']['accountId']
		self.email = json_data['data']['profile']['email']
		self.name = json_data['data']['profile']['name']
		return json_data

	def get_activity_log(self):
		"""
		Get datas about the activity log
		:return: activity log
		"""
		body = {"operationName": "GetActivityLog", "variables": {"from": 0, "size": 6}, "query": "query GetActivityLog($from: Int, $size: Int) {\n  profile {\n    activities(from: $from, size: $size) {\n      ...Activity\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment Activity on Activity {\n  activityId\n  accountId\n  action\n  timestamp\n  seen\n  data {\n    ... on ListAxie {\n      ...ListAxie\n      __typename\n    }\n    ... on UnlistAxie {\n      ...UnlistAxie\n      __typename\n    }\n    ... on BuyAxie {\n      ...BuyAxie\n      __typename\n    }\n    ... on GiftAxie {\n      ...GiftAxie\n      __typename\n    }\n    ... on MakeAxieOffer {\n      ...MakeAxieOffer\n      __typename\n    }\n    ... on CancelAxieOffer {\n      ...CancelAxieOffer\n      __typename\n    }\n    ... on SyncExp {\n      ...SyncExp\n      __typename\n    }\n    ... on MorphToPetite {\n      ...MorphToPetite\n      __typename\n    }\n    ... on MorphToAdult {\n      ...MorphToAdult\n      __typename\n    }\n    ... on BreedAxies {\n      ...BreedAxies\n      __typename\n    }\n    ... on BuyLand {\n      ...BuyLand\n      __typename\n    }\n    ... on ListLand {\n      ...ListLand\n      __typename\n    }\n    ... on UnlistLand {\n      ...UnlistLand\n      __typename\n    }\n    ... on GiftLand {\n      ...GiftLand\n      __typename\n    }\n    ... on MakeLandOffer {\n      ...MakeLandOffer\n      __typename\n    }\n    ... on CancelLandOffer {\n      ...CancelLandOffer\n      __typename\n    }\n    ... on BuyItem {\n      ...BuyItem\n      __typename\n    }\n    ... on ListItem {\n      ...ListItem\n      __typename\n    }\n    ... on UnlistItem {\n      ...UnlistItem\n      __typename\n    }\n    ... on GiftItem {\n      ...GiftItem\n      __typename\n    }\n    ... on MakeItemOffer {\n      ...MakeItemOffer\n      __typename\n    }\n    ... on CancelItemOffer {\n      ...CancelItemOffer\n      __typename\n    }\n    ... on ListBundle {\n      ...ListBundle\n      __typename\n    }\n    ... on UnlistBundle {\n      ...UnlistBundle\n      __typename\n    }\n    ... on BuyBundle {\n      ...BuyBundle\n      __typename\n    }\n    ... on MakeBundleOffer {\n      ...MakeBundleOffer\n      __typename\n    }\n    ... on CancelBundleOffer {\n      ...CancelBundleOffer\n      __typename\n    }\n    ... on AddLoomBalance {\n      ...AddLoomBalance\n      __typename\n    }\n    ... on WithdrawFromLoom {\n      ...WithdrawFromLoom\n      __typename\n    }\n    ... on AddFundBalance {\n      ...AddFundBalance\n      __typename\n    }\n    ... on WithdrawFromFund {\n      ...WithdrawFromFund\n      __typename\n    }\n    ... on TopupRoninWeth {\n      ...TopupRoninWeth\n      __typename\n    }\n    ... on WithdrawRoninWeth {\n      ...WithdrawRoninWeth\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment ListAxie on ListAxie {\n  axieId\n  priceFrom\n  priceTo\n  duration\n  txHash\n  __typename\n}\n\nfragment UnlistAxie on UnlistAxie {\n  axieId\n  txHash\n  __typename\n}\n\nfragment BuyAxie on BuyAxie {\n  axieId\n  price\n  owner\n  txHash\n  __typename\n}\n\nfragment GiftAxie on GiftAxie {\n  axieId\n  destination\n  txHash\n  __typename\n}\n\nfragment MakeAxieOffer on MakeAxieOffer {\n  axieId\n  price\n  txHash\n  __typename\n}\n\nfragment CancelAxieOffer on CancelAxieOffer {\n  axieId\n  txHash\n  __typename\n}\n\nfragment SyncExp on SyncExp {\n  axieId\n  exp\n  txHash\n  __typename\n}\n\nfragment MorphToPetite on MorphToPetite {\n  axieId\n  txHash\n  __typename\n}\n\nfragment MorphToAdult on MorphToAdult {\n  axieId\n  txHash\n  __typename\n}\n\nfragment BreedAxies on BreedAxies {\n  sireId\n  matronId\n  lovePotionAmount\n  txHash\n  __typename\n}\n\nfragment BuyLand on BuyLand {\n  row\n  col\n  price\n  owner\n  txHash\n  __typename\n}\n\nfragment ListLand on ListLand {\n  row\n  col\n  priceFrom\n  priceTo\n  duration\n  txHash\n  __typename\n}\n\nfragment UnlistLand on UnlistLand {\n  row\n  col\n  txHash\n  __typename\n}\n\nfragment GiftLand on GiftLand {\n  row\n  col\n  destination\n  txHash\n  __typename\n}\n\nfragment MakeLandOffer on MakeLandOffer {\n  row\n  col\n  price\n  txHash\n  __typename\n}\n\nfragment CancelLandOffer on CancelLandOffer {\n  row\n  col\n  txHash\n  __typename\n}\n\nfragment BuyItem on BuyItem {\n  tokenId\n  itemAlias\n  price\n  owner\n  txHash\n  __typename\n}\n\nfragment ListItem on ListItem {\n  tokenId\n  itemAlias\n  priceFrom\n  priceTo\n  duration\n  txHash\n  __typename\n}\n\nfragment UnlistItem on UnlistItem {\n  tokenId\n  itemAlias\n  txHash\n  __typename\n}\n\nfragment GiftItem on GiftItem {\n  tokenId\n  itemAlias\n  destination\n  txHash\n  __typename\n}\n\nfragment MakeItemOffer on MakeItemOffer {\n  tokenId\n  itemAlias\n  price\n  txHash\n  __typename\n}\n\nfragment CancelItemOffer on CancelItemOffer {\n  tokenId\n  itemAlias\n  txHash\n  __typename\n}\n\nfragment BuyBundle on BuyBundle {\n  listingIndex\n  price\n  owner\n  txHash\n  __typename\n}\n\nfragment ListBundle on ListBundle {\n  numberOfItems\n  priceFrom\n  priceTo\n  duration\n  txHash\n  __typename\n}\n\nfragment UnlistBundle on UnlistBundle {\n  listingIndex\n  txHash\n  __typename\n}\n\nfragment MakeBundleOffer on MakeBundleOffer {\n  listingIndex\n  price\n  txHash\n  __typename\n}\n\nfragment CancelBundleOffer on CancelBundleOffer {\n  listingIndex\n  txHash\n  __typename\n}\n\nfragment AddLoomBalance on AddLoomBalance {\n  amount\n  senderAddress\n  receiverAddress\n  txHash\n  __typename\n}\n\nfragment WithdrawFromLoom on WithdrawFromLoom {\n  amount\n  senderAddress\n  receiverAddress\n  txHash\n  __typename\n}\n\nfragment AddFundBalance on AddFundBalance {\n  amount\n  senderAddress\n  txHash\n  __typename\n}\n\nfragment WithdrawFromFund on WithdrawFromFund {\n  amount\n  receiverAddress\n  txHash\n  __typename\n}\n\nfragment WithdrawRoninWeth on WithdrawRoninWeth {\n  amount\n  receiverAddress\n  txHash\n  receiverAddress\n  __typename\n}\n\nfragment TopupRoninWeth on TopupRoninWeth {\n  amount\n  receiverAddress\n  txHash\n  receiverAddress\n  __typename\n}\n"}
		r = requests.post(self.url, headers=self.headers, json=body)
		try:
			json_data = json.loads(r.text)
		except ValueError as e:
			return e
		return json_data['data']['profile']['activities']

	def get_profile_name(self, ronin_address=''):
		"""
		Get the profile name of a ronin address
		:param ronin_address: The target ronin account
		:return: The name of the account
		"""
		if ronin_address == '':
			ronin_address = self.ronin_address
		body = {"operationName": "GetProfileNameByRoninAddress", "variables": {"roninAddress": ronin_address}, "query": "query GetProfileNameByRoninAddress($roninAddress: String!) {\n  publicProfileWithRoninAddress(roninAddress: $roninAddress) {\n    accountId\n    name\n    __typename\n  }\n}\n"}
		r = requests.post(self.url, headers=self.headers, json=body)
		try:
			json_data = json.loads(r.text)
		except ValueError as e:
			return e
		return json_data['data']['publicProfileWithRoninAddress']['name']

	def rename_account(self, new_name):
		body = {"operationName": "RenameAxie", "variables": {"axieId": str(new_name),"name": str(new_name) }, "query": "mutation RenameAxie($axieId: ID!, $name: String!) {\n  renameAxie(axieId: $axieId, name: $name) {\n    result\n    __typename\n  }\n}\n"}
		try:
			r = requests.post(self.url, headers=self.headers, json=body)
			json_data = json.loads(r.text)
		except ValueError as e:
			return e
		if json_data['data'] is None:
			return json_data['errors']['message']
		return json_data['data']['renameAxie']['result']

	def get_public_profile(self, ronin_address=''):
		"""
		Get infos about the given ronin address
		:param ronin_address: The target ronin account
		:return: Public datas of the ronin account
		"""
		if ronin_address == '':
			ronin_address = self.ronin_address
		body = {"operationName": "GetProfileByRoninAddress", "variables": {"roninAddress": ronin_address}, "query": "query GetProfileByRoninAddress($roninAddress: String!) {\n  publicProfileWithRoninAddress(roninAddress: $roninAddress) {\n    ...Profile\n    __typename\n  }\n}\n\nfragment Profile on PublicProfile {\n  accountId\n  name\n  addresses {\n    ...Addresses\n    __typename\n  }\n  __typename\n}\n\nfragment Addresses on NetAddresses {\n  ethereum\n  tomo\n  loom\n  ronin\n  __typename\n}\n"}
		r = requests.post(self.url, headers=self.headers, json=body)
		try:
			json_data = json.loads(r.text)
		except ValueError as e:
			return e
		return json_data['data']['publicProfileWithRoninAddress']

	def get_rank_mmr(self, ronin_address=''):
		"""
		Get the mmr and rank of the current account
		:return: Dict with MMR and rank
		"""
		if ronin_address == '':
			ronin_address = self.ronin_address
		params = {"client_id": ronin_address, "offset": 0, "limit": 0}

		# Try multiple times to avoid return 0
		for i in range(0, 5):
			try:
				r = requests.get(self.url_api + "last-season-leaderboard", params=params)
				json_data = json.loads(r.text)
				if json_data['success']:
					return {'mmr': int(json_data['items'][1]['elo']), 'rank': int(json_data['items'][1]['rank'])}
			except ValueError as e:
				return e
		return {'mmr': 0, 'rank': 0}


	def get_daily_slp(self):
		"""
		Get the daily SLP ratio based on SLP farmed between now and last claim
		:return: Dict with ratio and date
		"""
		unclaimed = self.get_unclaimed_slp()
		t = datetime.datetime.fromtimestamp(self.get_last_claim())
		days = (t - datetime.datetime.utcnow()).days * -1
		if days <= 0:
			return unclaimed
		return int(unclaimed / days)

	#############################################
	# Functions to interact with axies from web #
	#############################################

	def get_axie_list(self, ronin_address=''):
		"""
		Get informations about the axies in a specific account
		:param ronin_address: The ronin address of the target account
		:return: Data about the axies
		"""
		if ronin_address == '':
			ronin_address = self.ronin_address
		body = {"operationName": "GetAxieBriefList", "variables": {"from": 0, "size": 24, "sort": "IdDesc", "auctionType": "All", "owner": ronin_address, "criteria": {"region": None, "parts": None, "bodyShapes": None, "classes": None, "stages": None, "numMystic": None, "pureness": None, "title": None, "breedable": None, "breedCount": None, "hp":[],"skill":[],"speed":[],"morale":[]}},"query":"query GetAxieBriefList($auctionType: AuctionType, $criteria: AxieSearchCriteria, $from: Int, $sort: SortBy, $size: Int, $owner: String) {\n  axies(auctionType: $auctionType, criteria: $criteria, from: $from, sort: $sort, size: $size, owner: $owner) {\n    total\n    results {\n      ...AxieBrief\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment AxieBrief on Axie {\n  id\n  name\n  stage\n  class\n  breedCount\n  image\n  title\n  battleInfo {\n    banned\n    __typename\n  }\n  auction {\n    currentPrice\n    currentPriceUSD\n    __typename\n  }\n  parts {\n    id\n    name\n    class\n    type\n    specialGenes\n    __typename\n  }\n  __typename\n}\n"}
		try:
			r = requests.post(self.url, headers=self.headers, json=body)
			json_data = json.loads(r.text)
		except ValueError as e:
			return e
		return json_data['data']['axies']['results']

	def get_all_axie_list(self):
		"""
		Get informations about the axies in all the accounts
		:return: List with all axies datas
		"""
		res = list()
		for account in self.config['scholars']:
			axies = self.get_axie_list(self.config['scholars'][account]['ronin_address'])
			for axie in axies:
				res.append(axie)
		for axie in self.get_axie_list(self.config['personal']['ronin_address']):
			res.append(axie)
		return res

	def get_all_axie_class(self, axie_class, axies_datas=[]):
		"""
		Return all the axies of a specific class present in the scholarship
		:param axie_class: Plant, Bast, Bird, etc...
		:return: List of axie object of the specific class
		"""
		if not axies_datas:
			axies_datas = self.get_all_axie_list()
		l = list()
		for axie in axies_datas:
			if axie['class'] is not None and axie['class'].lower() == axie_class.lower():
				l.append(axie)
		return l

	def get_axie_image(self, axie_id):
		"""
		Get the image link to an axie
		:param axie_id: String ID of the axie you are targeting
		:return: Link to the image
		"""
		body = {"operationName": "GetAxieMetadata", "variables": {"axieId": axie_id}, "query": "query GetAxieMetadata($axieId: ID!) {\n  axie(axieId: $axieId) {\n    id\n    image\n    __typename\n  }\n}\n"}
		try:
			r = requests.post(self.url, headers=self.headers, json=body)
			json_data = json.loads(r.text)
		except ValueError as e:
			return e
		return json_data['data']['axie']['image']

	def get_number_of_axies(self):
		"""
		Get the number of axies in the account
		:return: the number of axies
		"""
		axies = self.get_axie_list()
		return len(axies)

	def download_axie_image(self, axie_id):
		"""
		Download the image of an axie and return the path
		:param axie_id: ID of the axie
		:return: Path of the image
		"""
		axie_id = str(axie_id)
		path = './img/axies/' + axie_id + '.png'
		dir = os.path.join(".", "img", "axies")
		if not os.path.exists(dir):
			os.mkdir(dir)

		if os.path.exists(path):
			return path

		img_data = requests.get('https://storage.googleapis.com/assets.axieinfinity.com/axies/'+axie_id+'/axie/axie-full-transparent.png').content
		if len(img_data) <= 500:
			return './img/axies/egg.png'
		with open(path, 'ab') as img:
			img.write(img_data)
		return path

	def get_axies_imageline(self):
		"""
		Get the path to the picture containing the 3 axies merged horizontally
		:return: Path of the new picture
		"""
		try:
			axies = self.get_axie_list()
			l = list()
			for axie in axies:
				l.append(self.download_axie_image(axie['id']))
			if len(l) < 3:
				return 'Error: not enough axies on the account'
		except ValueError as e:
			return e
		return pyaxie_utils.merge_images(l[0], l[1], l[2], self.name)

	def get_axie_detail(self, axie_id):
		"""
		Get informations about an Axie based on its ID
		:param axie_id: string ID of the axie
		:return: A dict with the adatas of the axie
		"""
		body = {"operationName": "GetAxieDetail", "variables": {"axieId": axie_id}, "query": "query GetAxieDetail($axieId: ID!) {\n  axie(axieId: $axieId) {\n    ...AxieDetail\n    __typename\n  }\n}\n\nfragment AxieDetail on Axie {\n  id\n  image\n  class\n  chain\n  name\n  genes\n  owner\n  birthDate\n  bodyShape\n  class\n  sireId\n  sireClass\n  matronId\n  matronClass\n  stage\n  title\n  breedCount\n  level\n  figure {\n    atlas\n    model\n    image\n    __typename\n  }\n  parts {\n    ...AxiePart\n    __typename\n  }\n  stats {\n    ...AxieStats\n    __typename\n  }\n  auction {\n    ...AxieAuction\n    __typename\n  }\n  ownerProfile {\n    name\n    __typename\n  }\n  battleInfo {\n    ...AxieBattleInfo\n    __typename\n  }\n  children {\n    id\n    name\n    class\n    image\n    title\n    stage\n    __typename\n  }\n  __typename\n}\n\nfragment AxieBattleInfo on AxieBattleInfo {\n  banned\n  banUntil\n  level\n  __typename\n}\n\nfragment AxiePart on AxiePart {\n  id\n  name\n  class\n  type\n  specialGenes\n  stage\n  abilities {\n    ...AxieCardAbility\n    __typename\n  }\n  __typename\n}\n\nfragment AxieCardAbility on AxieCardAbility {\n  id\n  name\n  attack\n  defense\n  energy\n  description\n  backgroundUrl\n  effectIconUrl\n  __typename\n}\n\nfragment AxieStats on AxieStats {\n  hp\n  speed\n  skill\n  morale\n  __typename\n}\n\nfragment AxieAuction on Auction {\n  startingPrice\n  endingPrice\n  startingTimestamp\n  endingTimestamp\n  duration\n  timeLeft\n  currentPrice\n  currentPriceUSD\n  suggestedPrice\n  seller\n  listingIndex\n  state\n  __typename\n}\n"}
		try:
			r = requests.post(self.url, headers=self.headers, json=body)
			json_data = json.loads(r.text)
		except ValueError as e:
			return None
		return json_data['data']['axie']

	def get_axie_name(self, axie_id):
		"""
		Get the name of an axie based on his ID
		:param axie_id: The id of the axie
		:return: Name of the axie
		"""
		body = {"operationName": "GetAxieName", "variables": {"axieId": axie_id}, "query": "query GetAxieName($axieId: ID!) {\n  axie(axieId: $axieId) {\n    ...AxieName\n    __typename\n  }\n}\n\nfragment AxieName on Axie {\n  name\n  __typename\n}\n"}
		try:
			r = requests.post(self.url, headers=self.headers, json=body)
			json_data = json.loads(r.text)
		except ValueError as e:
			return e
		return json_data['data']['axie']['name']

	def get_axie_stats(self, axie_id):
		"""
		Get axie 4 basic stats (HP, morale, skill, speed)
		:param axie_id: String ID of the axie
		:return: Dict with the stats
		"""
		data = self.get_axie_detail(axie_id)
		return data['stats']

	def get_axie_parts(self, axie_id):
		"""
		Get axies body parts from an axie ID
		:param axie_id: String ID of the axie
		:return: Dict with the differents body parts
		"""
		data = self.get_axie_detail(axie_id)
		return data['parts']

	def get_axie_class(self, axie_id):
		"""
		Get the class of an axie based on it's ID
		:param axie_id: String ID of the axie
		:return: Dict with the differents body parts
		"""
		data = self.get_axie_detail(axie_id)
		return data['class']

	def get_axie_children(self, id=0, axie_data={}):
		"""
		Get the children of an axie on given id OR given axie datas
		:param id: id of the axie
		:param axie_data: axie_datas
		:return: list of id of the children
		"""
		axie = self.get_axie_detail(id) if axie_data == {} else axie_data
		l = list()
		for children in axie['children']:
			l.append(int(children['id']))
		return l

	def rename_axie(self, axie_id, new_name):
		"""
		Rename an axie
		:param axie_id: The id of the axie to rename
		:param new_name: The new name of the axie
		:return: True/False or error
		"""
		body = {"operationName": "RenameAxie", "variables": {"axieId": str(axie_id),"name": str(new_name) }, "query": "mutation RenameAxie($axieId: ID!, $name: String!) {\n  renameAxie(axieId: $axieId, name: $name) {\n    result\n    __typename\n  }\n}\n"}
		try:
			r = requests.post(self.url, headers=self.headers, json=body)
			json_data = json.loads(r.text)
			pprint(json_data)
		except ValueError as e:
			return e
		if json_data['data'] is None:
			return False
		return json_data['data']['renameAxie']['result']

	###############################################
	# Functions to interact with stored axie data #
	###############################################

	def save_axie(self, axie_data):
		"""
		Save an axie details to the local axie_list
		:param axie_data:
		:param axie_list: Path of the axie_list file
		"""
		axie_list = self.axie_list()
		axie_id = axie_data['id']
		if axie_list:
			axie_list.update({axie_id: axie_data})
		else:
			axie_list = {axie_id: axie_data}
		f = open(self.axie_list_path, 'a')
		yaml.safe_dump(axie_list, f)
		f.close()

	def check_axie(self, axie_id):
		"""
		Check if we have this axie data locally
		:param axie_id: String of the ID of the axie to check
		:return: Data of the axie or None if not locally
		"""
		with open(self.axie_list_path) as f:
			data = yaml.safe_load(f)

		for val in data:
			if val == str(axie_id):
				return val
		return []

	def update_axie_list(self):
		"""
		Update the local axie_list with the new datas
		"""
		axie_list = self.axie_list()
		new = {}

		for axie in axie_list:
			new[axie['id']] = self.get_axie_detail(axie['id'])
		with open(self.axie_list_path, 'w') as outfile:
			yaml.safe_dump(new, outfile)

	def axie_list(self):
		"""
		Get the list of axies stored locally
		:return: List of axie data
		"""
		if os.stat(self.axie_list_path).st_size > 3:
			f = open(self.axie_list_path, 'r')
			data = yaml.safe_load(f)
			f.close()
			if data:
				return data
		return None

	def axie_detail(self, axie_id):
		"""
		Retrieve local details about an axie
		:param axie_id: The ID of the axie
		:return: Informations about the axie
		"""
		data = self.axie_list()
		if data:
			return data[str(axie_id)]
		return None

	def axie_infos(self, axie_id, key):
		"""
		Retrieve locally specific informations (key) about axie
		:param axie_id: String ID of the axie
		:param key: 'parts' or 'class' or 'stats' (list on documentation)
		:return: Information about the axie
		"""
		if self.check_axie(axie_id):
			return self.axie_detail(axie_id)[key]
		return "This axie is not registered : " + str(axie_id)

	def axie_link(self, axie_id):
		"""
		Return an URL to the axie page
		:param axie_id: Id of the axie
		:return: URL of the axie
		"""
		url = 'https://marketplace.axieinfinity.com/axie/'
		return url + str(axie_id)

	###################
	# Ronin functions #
	###################

	def get_ronin_web3(self):
		"""
		:return: Return the ronin web3
		"""
		web3 = Web3(Web3.HTTPProvider('https://proxy.roninchain.com/free-gas-rpc'))
		return web3

	def get_slp_contract(self, ronin_web3, slp_abi_path):
		"""
		:param ronin_web3: ronin web3 object
		:param slp_abi_path: ABI for SLP
		:return: The contract to interact with
		"""
		slp_contract_address = "0xa8754b9fa15fc18bb59458815510e40a12cd2014"
		with open(slp_abi_path) as f:
			try:
				slp_abi = json.load(f)
			except ValueError as e:
				return e
		contract = ronin_web3.eth.contract(address=w3.toChecksumAddress(slp_contract_address), abi=slp_abi)
		self.slp_contract = contract
		return contract

	def get_axie_contract(self, ronin_web3):
		slp_contract_address = "0x32950db2a7164ae833121501c797d79e7b79d74c"
		with open(self.axie_abi_path) as f:
			try:
				slp_abi = json.load(f)
			except ValueError as e:
				return e
		contract = ronin_web3.eth.contract(address=w3.toChecksumAddress(slp_contract_address), abi=slp_abi)
		self.slp_contract = contract
		return contract


	def get_claimed_slp(self, address=''):
		"""
		:param address: Ronin address to check
		:return: The amount of claimed SLP
		"""
		if address == '':
			address = self.ronin_address
		try:
			response = requests.get(self.url_api + f"clients/{address}/items/1", headers=self.headers, data="")
			data = json.loads(response.text)
		except ValueError as e:
			return e

		balance = data['blockchain_related']['balance']
		if balance is None:
			return 0

		return int(balance)

	def get_unclaimed_slp(self, address=''):
		"""
		:param address: Ronin address to check
		:return: The amount of unclaimed SLP
		"""
		if address == '':
			address = self.ronin_address
		try:
			response = requests.get(self.url_api + f"clients/{address}/items/1", headers=self.headers, data="")
			result = response.json()
		except ValueError as e:
			return e
		if result is None:
			return 0

		balance = -1
		if 'blockchain_related' in result:
			balance = result['blockchain_related']['balance']
		else:
			return balance
		if balance is None:
			balance = 0

		res = result["total"]
		if res is None:
			res = 0
		return int(res - balance)

	def get_last_claim(self, address=''):
		"""
		Return the last time SLP was claimed for this account
		:param address: Ronin address
		:return: Time in sec
		"""
		if address == '':
			address = self.ronin_address

		try:
			response = requests.get(self.url_api + f"clients/{address}/items/1", headers=self.headers, data="")
			result = response.json()
		except ValueError as e:
			return e

		return int(result["last_claimed_item_at"])

	def claim_slp(self):
		"""
		Claim SLP on the account.
		:return: Transaction of the claim
		"""
		print("\nClaiming SLP for : ", self.name)

		if datetime.datetime.utcnow() + timedelta(days=-14) < datetime.datetime.fromtimestamp(self.get_last_claim()):
			return 'Error: Too soon to claim or already claimed'

		slp_claim = {
			'address': self.ronin_address,
			'private_key': self.private_key,
			'state': {"signature": None}
		}
		access_token = self.access_token
		custom_headers = self.headers.copy()
		custom_headers["authorization"] = f"Bearer {access_token}"
		response = requests.post(self.url_api + f"clients/{self.ronin_address}/items/1/claim", headers=custom_headers, json="")

		if response.status_code != 200:
			print(response.text)
			return

		result = response.json()["blockchain_related"]["signature"]
		if result is None:
			return 'Error: Nothing to claim'

		checksum_address = w3.toChecksumAddress(self.ronin_address)
		nonce = self.ronin_web3.eth.get_transaction_count(checksum_address)
		slp_claim['state']["signature"] = result["signature"].replace("0x", "")
		claim_txn = self.slp_contract.functions.checkpoint(checksum_address, result["amount"], result["timestamp"],
						slp_claim['state']["signature"]).buildTransaction({'gas': 1000000, 'gasPrice': 0, 'nonce': nonce})
		signed_txn = self.ronin_web3.eth.account.sign_transaction(claim_txn, private_key=bytearray.fromhex(self.private_key.replace("0x", "")))

		self.ronin_web3.eth.send_raw_transaction(signed_txn.rawTransaction)
		txn = self.ronin_web3.toHex(self.ronin_web3.keccak(signed_txn.rawTransaction))
		return txn if self.wait_confirmation(txn) else "Error : Transaction " + str(txn) + "reverted by EVM (Ethereum Virtual machine)"

	def transfer_slp(self, to_address, amount):
		"""
		Transfer SLP from pyaxie ronin address to the to_address
		:param to_address: Receiver of the SLP. Format : 0x
		:param amount: Amount of SLP to send
		:return: Transaction hash
		"""
		if amount < 1 or not Web3.isAddress(to_address):
			return {"error": "Make sure that the amount is not under 1 and the **to_address** is correct."}

		transfer_txn = self.slp_contract.functions.transfer(w3.toChecksumAddress(to_address), amount).buildTransaction({
			'chainId': 2020,
			'gas': 100000,
			'gasPrice': Web3.toWei('0', 'gwei'),
			'nonce': self.ronin_web3.eth.get_transaction_count(w3.toChecksumAddress(self.ronin_address))
		})
		private_key = bytearray.fromhex(self.private_key.replace("0x", ""))
		signed_txn = self.ronin_web3.eth.account.sign_transaction(transfer_txn, private_key=private_key)

		self.ronin_web3.eth.send_raw_transaction(signed_txn.rawTransaction)
		txn = self.ronin_web3.toHex(self.ronin_web3.keccak(signed_txn.rawTransaction))
		return txn if self.wait_confirmation(txn) else "Error : Transaction " + str(txn) + " reverted by EVM (Ethereum Virtual machine)"

	def wait_confirmation(self, txn):
		"""
		Wait for a transaction to finish
		:param txn: the transaction to wait
		:return: True or False depending if transaction succeed
		"""
		while True:
			try:
				recepit = self.ronin_web3.eth.get_transaction_receipt(txn)
				success = True if recepit["status"] == 1 else False
				break
			except exceptions.TransactionNotFound:
				time.sleep(5)
		return success

	def payout(self):
		"""
		Send money to the scholar and to the manager/academy or directly to manager if manager called
		:return: List of 2 transactions hash : scholar and manager
		"""
		self.claim_slp()

		txns = list()
		slp_balance = self.get_claimed_slp()
		scholar_payout_amount = math.ceil(slp_balance * self.payout_percentage)
		academy_payout_amount = slp_balance - scholar_payout_amount

		if slp_balance < 1:
			return ["Error: Nothing to send.", "Error: Nothing to send."]

		if self.payout_percentage == 0:
			print("Sending all {} SLP to you : {} ".format(academy_payout_amount, self.config['personal']['ronin_address']))
			txns.append(str(self.transfer_slp(self.config['personal']['ronin_address'], academy_payout_amount + scholar_payout_amount)))
			txns.append("Nothing to send to scholar")
			return txns
		else:
			# TODO(igaskin) change second field to guild name variable
			print("Sending {} SLP to {} : {} ".format(academy_payout_amount, "Axie Amigos", self.config['personal']['ronin_address'].replace('ronin:', '0x')))
			txns.append(str(self.transfer_slp(self.config['personal']['ronin_address'].replace('ronin:', '0x'), academy_payout_amount)))

			print("Sending {} SLP to {} : {} ".format(scholar_payout_amount, self.name, self.personal_ronin))
			txns.append(str(self.transfer_slp(self.personal_ronin, scholar_payout_amount)))
		return txns


	def get_breed_cost(self, nb=-1):
		"""
		Get the breeding cost
		:param nb: breed lvl (0-6)
		:return: dict with datas about the breeding costs
		"""
		breeds = {0: 150, 1: 300, 2: 450, 3: 750, 4: 1200, 5: 1950, 6: 3150}
		axs = self.get_price('axs')
		slp = self.get_price('slp')
		total = 0
		res = dict()

		for i in range(0, 7):
			breed_price = int((breeds[i] * slp) * 2 + (axs * 2))
			total += breed_price
			res[i] = {'price': breed_price, 'total_breed_price': total, 'average_price': int(total/(1+i))}

		if nb <= -1:
			return res
		return {nb, res[nb]}

	def get_prices_from_timestamp(self, timestamp):
		"""
		Get prices for AXS, SLP and ETH at given date
		:param timestamp: date in unix timestamp format
		:return: Dict with the prices of currencies at given date
		"""
		cg = CoinGeckoAPI()
		dt = datetime.datetime.fromtimestamp(timestamp)

		price_history = cg.get_coin_history_by_id(id='smooth-love-potion', date=dt.date().strftime('%d-%m-%Y'), vsCurrencies=['usd'])
		slp_price = price_history['market_data']['current_price']['usd']

		price_history = cg.get_coin_history_by_id(id='axie-infinity', date=dt.date().strftime('%d-%m-%Y'), vsCurrencies=['usd'])
		axs_price = price_history['market_data']['current_price']['usd']

		price_history = cg.get_coin_history_by_id(id='ethereum', date=dt.date().strftime('%d-%m-%Y'), vsCurrencies=['usd'])
		eth_price = price_history['market_data']['current_price']['usd']

		return {'slp': slp_price, 'axs': axs_price, 'eth': eth_price, 'date': timestamp}

	def ronin_txs(self, ronin_address=''):
		if ronin_address == '':
			ronin_address = self.config['personal']['ronin_address']

		url = "https://explorer.roninchain.com/api/txs/" + str(ronin_address) + "?size=10000"
		h = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36'}
		response = requests.get(url, headers=h)

		try:
			json_data = json.loads(response.text)
		except ValueError as e:
			return e
		return json_data['results']

	def get_axie_total_breed_cost(self, axie_id, txs={}):
		if not isinstance(axie_id, int):
			return "Error in axie ID."
		if txs == {}:
			txs = self.ronin_txs()

		children = self.get_axie_children(axie_id)
		total = 0
		l = list()
		for i in txs:
			if len(i['logs']) == 4 and len(i['logs'][3]['topics']) > 1 and int(i['logs'][3]['topics'][1], 16) in children:
				prices = self.get_prices_from_timestamp(i['timestamp'])
				slp_price = int(i['logs'][1]['data'], 16) * prices['slp']
				axs_price = prices['axs'] * 2
				l.append({'date': datetime.datetime.fromtimestamp(i['timestamp']).strftime('%d-%m-%Y'),
							'axs_price': round(prices['axs'], 2), 'slp_price': round(prices['slp'], 2),
							'breed_cost': round(slp_price + axs_price, 2), 'axs_cost': round(axs_price, 2),
							'slp_cost': round(slp_price, 2), 'axie_id': int(i['logs'][3]['topics'][1], 16)})
				total += slp_price + axs_price
		res = dict()
		res['total_breed_cost'] = round(total, 2)
		res['average_breed_cost'] = round(total / len(children), 2)
		res['details'] = l
		return res

	def get_account_balances(self, ronin_address=''):
		"""
		Get the different balances for a given account (AXS, SLP, WETH, AXIES)
		:param ronin_address: ronin address of the account
		:return: dict with currencies and amount
		"""
		if not ronin_address:
			ronin_address = self.config['personal']['ronin_address']

		url = "https://explorer.roninchain.com/api/tokenbalances/" + str(ronin_address).replace('ronin:', '0x')
		headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36'}
		response = requests.get(url, headers=headers)

		try:
			json_data = json.loads(response.text)
		except ValueError as e:
			return {'WETH': -1, 'AXS': -1, 'SLP': -1, 'axies': -1, 'ronin_address': ronin_address}

		res = {'WETH': 0, 'AXS': 0, 'SLP': 0, 'axies': 0, 'ronin_address': ronin_address}
		for data in json_data['results']:
			if data['token_symbol'] == 'WETH':
				res['WETH'] = round(int(data['balance']) / math.pow(10, 18), 6)
			elif data['token_symbol'] == 'AXS':
				res['AXS'] = round(int(data['balance']) / math.pow(10, 18), 2)
			elif data['token_symbol'] == 'SLP':
				res['SLP'] = int(data['balance'])
			elif data['token_symbol'] == 'AXIE':
				res['axies'] = int(data['balance'])
		return res

	def get_all_accounts_balances(self):
		l = list()
		l.append(self.config['personal']['ronin_address'])
		for account in self.config['scholars']:
			l.append(self.config['scholars'][account]['ronin_address'])

		res = list()
		for r in l:
			res.append(self.get_account_balances(r))
		return res



