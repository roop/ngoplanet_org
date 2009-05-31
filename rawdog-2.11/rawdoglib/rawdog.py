# rawdog: RSS aggregator without delusions of grandeur.
# Copyright 2003, 2004, 2005, 2006 Adam Sampson <ats@offog.org>
#
# rawdog is free software; you can redistribute and/or modify it
# under the terms of that license as published by the Free Software
# Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# rawdog is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with rawdog; see the file COPYING. If not, write to the Free
# Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301, USA, or see http://www.gnu.org/.

VERSION = "2.11"
STATE_VERSION = 2
import feedparser, feedfinder, plugins
from persister import Persistable, Persister
import os, time, sha, getopt, sys, re, cgi, socket, urllib2, calendar
import string, locale
from StringIO import StringIO
import types

try:
	import threading
	have_threading = 1
except:
	have_threading = 0

def set_socket_timeout(n):
	"""Set the system socket timeout."""
	if hasattr(socket, "setdefaulttimeout"):
		socket.setdefaulttimeout(n)
	else:
		# Python 2.2 and earlier need to use an external module.
		import timeoutsocket
		timeoutsocket.setDefaultSocketTimeout(n)

def get_system_encoding():
	"""Get the system encoding."""
	try:
		# This doesn't exist on Python 2.2.
		return locale.getpreferredencoding()
	except:
		return "UTF-8"

def safe_ftime(format, t):
	"""Format a time value into a string in the current locale (as
	time.strftime), but encode the result as ASCII HTML."""
	u = unicode(time.strftime(format, t), get_system_encoding())
	return encode_references(u)

def format_time(secs, config):
	"""Format a time and date nicely."""
	t = time.localtime(secs)
	format = config["datetimeformat"]
	if format is None:
		format = config["timeformat"] + ", " + config["dayformat"]
	return safe_ftime(format, t)

def encode_references(s):
	"""Encode characters in a Unicode string using HTML references."""
	r = StringIO()
	for c in s:
		n = ord(c)
		if n >= 128:
			r.write("&#" + str(n) + ";")
		else:
			r.write(c)
	v = r.getvalue()
	r.close()
	return v

# This list of block-level elements came from the HTML 4.01 specification.
block_level_re = re.compile(r'^\s*<(p|h1|h2|h3|h4|h5|h6|ul|ol|pre|dl|div|noscript|blockquote|form|hr|table|fieldset|address)[^a-z]', re.I)
def sanitise_html(html, baseurl, inline, config):
	"""Attempt to turn arbitrary feed-provided HTML into something
	suitable for safe inclusion into the rawdog output. The inline
	parameter says whether to expect a fragment of inline text, or a
	sequence of block-level elements."""
	if html is None:
		return None

	html = encode_references(html)
	type = "text/html"

	# sgmllib handles "<br/>/" as a SHORTTAG; this workaround from
	# feedparser.
	html = re.sub(r'(\S)/>', r'\1 />', html)
	html = feedparser._resolveRelativeURIs(html, baseurl, "UTF-8", type)
    # sanitizer removes videos from blogger - so dont sanitize
	# p = feedparser._HTMLSanitizer("UTF-8", type)
	# p.feed(html)
	# html = p.output()

	if not inline and config["blocklevelhtml"]:
		# If we're after some block-level HTML and the HTML doesn't
		# start with a block-level element, then insert a <p> tag
		# before it. This still fails when the HTML contains text, then
		# a block-level element, then more text, but it's better than
		# nothing.
		if block_level_re.match(html) is None:
			html = "<p>" + html

	if config["tidyhtml"]:
		import mx.Tidy
		args = { "wrap": 0, "numeric_entities": 1 }
		plugins.call_hook("mxtidy_args", config, args, baseurl, inline)
		output = mx.Tidy.tidy(html, None, None,
		                      **args)[2]
		html = output[output.find("<body>") + 6
		              : output.rfind("</body>")].strip()

	html = html.decode("UTF-8")
	box = plugins.Box(html)
	plugins.call_hook("clean_html", config, box, baseurl, inline)
	return box.value

def select_detail(details):
	"""Pick the preferred type of detail from a list of details. (If the
	argument isn't a list, treat it as a list of one.)"""
	types = {"text/html": 30,
	         "application/xhtml+xml": 20,
	         "text/plain": 10}

	if details is None:
		return None
	if type(details) is not list:
		details = [details]

	ds = []
	for detail in details:
		ctype = detail.get("type", None)
		if ctype is None:
			continue
		if types.has_key(ctype):
			score = types[ctype]
		else:
			score = 0
		if detail["value"] != "":
			ds.append((score, detail))
	ds.sort()

	if len(ds) == 0:
		return None
	else:
		return ds[-1][1]

def detail_to_html(details, inline, config, force_preformatted = False):
	"""Convert a detail hash or list of detail hashes as returned by
	feedparser into HTML."""
	detail = select_detail(details)
	if detail is None:
		return None

	if force_preformatted:
		html = "<pre>" + cgi.escape(detail["value"]) + "</pre>"
	elif detail["type"] == "text/plain":
		html = cgi.escape(detail["value"])
	else:
		html = detail["value"]

	if config["defines"].has_key("feedoutput") and config["defines"]["feedoutput"]:
		html = cgi.escape(html)

	return sanitise_html(html, detail["base"], inline, config)

def author_to_html(entry, feedurl, config):
	"""Convert feedparser author information to HTML."""
	author_detail = entry.get("author_detail")

	if author_detail is not None and author_detail.has_key("name"):
		name = author_detail["name"]
	else:
		name = entry.get("author")

	url = None
	fallback = "author"
	if author_detail is not None:
		if author_detail.has_key("url"):
			url = author_detail["url"]
		elif author_detail.has_key("email") and author_detail["email"] is not None:
			url = "mailto:" + author_detail["email"]
		if author_detail.has_key("email") and author_detail["email"] is not None:
			fallback = author_detail["email"]
		elif author_detail.has_key("url") and author_detail["url"] is not None:
			fallback = author_detail["url"]

	if name == "":
		name = fallback

	if url is None:
		html = name
	else:
		html = "<a href=\"" + cgi.escape(url) + "\">" + cgi.escape(name) + "</a>"

	# We shouldn't need a base URL here anyway.
	return sanitise_html(html, feedurl, True, config)

def string_to_html(s, config):
	"""Convert a string to HTML."""
	return sanitise_html(cgi.escape(s), "", True, config)

template_re = re.compile(r'(__.*?__)')
def fill_template(template, bits):
	"""Expand a template, replacing __x__ with bits["x"], and only
	including sections bracketed by __if_x__ .. [__else__ ..]
	__endif__ if bits["x"] is not "". If not bits.has_key("x"),
	__x__ expands to ""."""
	result = plugins.Box()
	plugins.call_hook("fill_template", template, bits, result)
	if result.value is not None:
		return result.value

	encoding = get_system_encoding()

	f = StringIO()
	if_stack = []
	def write(s):
		if not False in if_stack:
			f.write(s)
	for part in template_re.split(template):
		if part.startswith("__") and part.endswith("__"):
			key = part[2:-2]
			if key.startswith("if_"):
				k = key[3:]
				if_stack.append(bits.has_key(k) and bits[k] != "")
			elif key == "endif":
				if if_stack != []:
					if_stack.pop()
			elif key == "else":
				if if_stack != []:
					if_stack.append(not if_stack.pop())
			elif bits.has_key(key):
				if type(bits[key]) == types.UnicodeType:
					write(bits[key].encode(encoding))
				else:
					write(bits[key])
		else:
			write(part)
	return f.getvalue()

file_cache = {}
def load_file(name):
	"""Read the contents of a file, caching the result so we don't have to
	read the file multiple times."""
	if not file_cache.has_key(name):
		f = open(name)
		file_cache[name] = f.read()
		f.close()
	return file_cache[name]

def write_ascii(f, s, config):
	"""Write the string s, which should only contain ASCII characters, to
	file f; if it isn't encodable in ASCII, then print a warning message
	and write UTF-8."""
	try:
		f.write(s)
	except UnicodeEncodeError, e:
		config.bug("Error encoding output as ASCII; UTF-8 has been written instead.\n", e)
		f.write(s.encode("UTF-8"))

def short_hash(s):
	"""Return a human-manipulatable 'short hash' of a string."""
	return sha.new(s).hexdigest()[-8:]

def decode_structure(struct, encoding):
	"""Walk through a structure returned by feedparser, decoding any
	strings that haven't already been converted to Unicode."""
	def is_dict(t):
		return (t is dict) or (t is feedparser.FeedParserDict)
	for (key, value) in struct.items():
		if type(value) is str:
			try:
				struct[key] = value.decode(encoding)
			except:
				# If the encoding's invalid, at least preserve
				# the byte stream.
				struct[key] = value.decode("ISO-8859-1")
		elif is_dict(type(value)):
			decode_structure(value, encoding)
		elif type(value) is list:
			for item in value:
				if is_dict(type(item)):
					decode_structure(item, encoding)

non_alphanumeric_re = re.compile(r'<[^>]*>|\&[^\;]*\;|[^a-z0-9]')
class Feed:
	"""An RSS feed."""

	def __init__(self, url):
		self.url = url
		self.period = 30 * 60
		self.args = {}
		self.etag = None
		self.modified = None
		self.last_update = 0
		self.feed_info = {}

	def needs_update(self, now):
		"""Return 1 if it's time to update this feed, or 0 if its
		update period has not yet elapsed."""
		if (now - self.last_update) < self.period:
			return 0
		else:
			return 1

	def fetch(self, rawdog, config):
		"""Fetch the current set of articles from the feed."""

		handlers = []

		proxies = {}
		for key, arg in self.args.items():
			if key.endswith("_proxy"):
				proxies[key[:-6]] = arg
		if len(proxies) != 0:
			handlers.append(urllib2.ProxyHandler(proxies))

		if self.args.has_key("proxyuser") and self.args.has_key("proxypassword"):
			mgr = DummyPasswordMgr((self.args["proxyuser"], self.args["proxypassword"]))
			handlers.append(urllib2.ProxyBasicAuthHandler(mgr))

		plugins.call_hook("add_urllib2_handlers", rawdog, config, self, handlers)

		auth_creds = None
		if self.args.has_key("user") and self.args.has_key("password"):
			auth_creds = (self.args["user"], self.args["password"])

		use_im = True
		if self.get_keepmin(config) == 0 or config["currentonly"]:
			use_im = False

		try:
			return feedparser.parse(self.url,
				etag = self.etag,
				modified = self.modified,
				agent = "rawdog/" + VERSION,
				handlers = handlers,
				auth_creds = auth_creds,
				use_im = use_im)
		except:
			return None

	def update(self, rawdog, now, config, p):
		"""Add new articles from a feed to the collection.
		Returns True if any articles were read, False otherwise."""

		status = None
		if p is not None:
			status = p.get("status")
		self.last_update = now

		error = None
		non_fatal = False
		old_url = self.url
		if p is None:
			error = "Error fetching or parsing feed."
		elif status is None and len(p["feed"]) == 0:
			if config["ignoretimeouts"]:
				return False
			else:
				error = "Timeout while reading feed."
		elif status is None:
			# Fetched by some protocol that doesn't have status.
			pass
		elif status == 301:
			# Permanent redirect. The feed URL needs changing.

			error = "New URL:     " + p["url"] + "\n"
			error += "The feed has moved permanently to a new URL.\n"
			if config["changeconfig"]:
				rawdog.change_feed_url(self.url, p["url"])
				error += "The config file has been updated automatically."
			else:
				error += "You should update its entry in your config file."
			non_fatal = True
		elif status in [403, 410]:
			# The feed is disallowed or gone. The feed should be unsubscribed.
			error = "The feed has gone.\n"
			error += "You should remove it from your config file."
		elif status / 100 in [4, 5]:
			# Some sort of client or server error. The feed may need unsubscribing.
			error = "The feed returned an error.\n"
			error += "If this condition persists, you should remove it from your config file."

		plugins.call_hook("feed_fetched", rawdog, config, self, p, error, non_fatal)

		if error is not None:
			print >>sys.stderr, "Feed:        " + old_url
			if status is not None:
				print >>sys.stderr, "HTTP Status: " + str(status)
			print >>sys.stderr, error
			print >>sys.stderr
			if not non_fatal:
				return False

		decode_structure(p, p.get("encoding") or "UTF-8")

		self.etag = p.get("etag")
		self.modified = p.get("modified")

		# In the event that the feed hasn't changed, then both channel
		# and feed will be empty. In this case we return 0 so that
		# we know not to expire articles that came from this feed.
		if len(p["entries"]) == 0:
			return False

		self.feed_info = p["feed"]
		feed = self.url
		articles = rawdog.articles

		seen = {}
		sequence = 0
		for entry_info in p["entries"]:
			article = Article(feed, entry_info, now, sequence)
			ignore = plugins.Box(False)
			plugins.call_hook("article_seen", rawdog, config, article, ignore)
			if ignore.value:
				continue
			seen[article.hash] = True
			sequence += 1

			if articles.has_key(article.hash):
				articles[article.hash].update_from(article, now)
				plugins.call_hook("article_updated", rawdog, config, article, now)
			else:
				articles[article.hash] = article
				plugins.call_hook("article_added", rawdog, config, article, now)

		if config["currentonly"]:
			for (hash, a) in articles.items():
				if a.feed == feed and not seen.has_key(hash):
					del articles[hash]

		return True

	def get_html_name(self, config):
		if self.feed_info.has_key("title_detail"):
			r = detail_to_html(self.feed_info["title_detail"], True, config)
		elif self.feed_info.has_key("link"):
			r = string_to_html(self.feed_info["link"], config)
		else:
			r = string_to_html(self.url, config)
		if r is None:
			r = ""
		return r

	def get_html_link(self, config):
		s = self.get_html_name(config)
		if self.feed_info.has_key("link"):
			return '<a href="' + string_to_html(self.feed_info["link"], config) + '">' + s + '</a>'
		else:
			return s

	def get_id(self, config):
		if self.args.has_key("id"):
			return self.args["id"]
		else:
			r = self.get_html_name(config).lower()
			return non_alphanumeric_re.sub('', r)

	def get_keepmin(self, config):
		try:
			return int(self.args["keepmin"])
		except:
			return config["keepmin"]

class Article:
	"""An article retrieved from an RSS feed."""

	def __init__(self, feed, entry_info, now, sequence):
		self.feed = feed
		self.entry_info = entry_info
		self.sequence = sequence

		modified = entry_info.get("modified_parsed")
		self.date = None
		if modified is not None:
			try:
				self.date = calendar.timegm(modified)
			except OverflowError:
				pass

		self.hash = self.compute_hash()

		self.last_seen = now
		self.added = now

	def compute_hash(self):
		h = sha.new()
		def add_hash(s):
			h.update(s.encode("UTF-8"))

		add_hash(self.feed)
		entry_info = self.entry_info
		if entry_info.has_key("title_raw"):
			add_hash(entry_info["title_raw"])
		if entry_info.has_key("link"):
			add_hash(entry_info["link"])
		if entry_info.has_key("content"):
			for content in entry_info["content"]:
				add_hash(content["value_raw"])
		if entry_info.has_key("summary_detail"):
			add_hash(entry_info["summary_detail"]["value_raw"])

		return h.hexdigest()

	def update_from(self, new_article, now):
		"""Update this article's contents from a newer article that's
		been identified to be the same (i.e. has hashed the same, but
		might have other changes that aren't part of the hash)."""
		self.entry_info = new_article.entry_info
		self.sequence = new_article.sequence
		self.date = new_article.date
		self.last_seen = now

	def can_expire(self, now, config):
		return ((now - self.last_seen) > config["expireage"])

class DayWriter:
	"""Utility class for writing day sections into a series of articles."""

	def __init__(self, file, config):
		self.lasttime = [-1, -1, -1, -1, -1]
		self.file = file
		self.counter = 0
		self.config = config

	def start_day(self, tm):
		print >>self.file, '<div class="day">'
		day = safe_ftime(self.config["dayformat"], tm)
		print >>self.file, '<h2>' + day + '</h2>'
		self.counter += 1

	def start_time(self, tm):
		print >>self.file, '<div class="time">'
		clock = safe_ftime(self.config["timeformat"], tm)
		print >>self.file, '<h3>' + clock + '</h3>'
		self.counter += 1

	def time(self, s):
		tm = time.localtime(s)
		if tm[:3] != self.lasttime[:3] and self.config["daysections"]:
			self.close(0)
			self.start_day(tm)
		if tm[:6] != self.lasttime[:6] and self.config["timesections"]:
			if self.config["daysections"]:
				self.close(1)
			else:
				self.close(0)
			self.start_time(tm)
		self.lasttime = tm

	def close(self, n = 0):
		while self.counter > n:
			print >>self.file, "</div>"
			self.counter -= 1

def parse_time(value, default = "m"):
	"""Parse a time period with optional units (s, m, h, d, w) into a time
	in seconds. If no unit is specified, use minutes by default; specify
	the default argument to change this. Raises ValueError if the format
	isn't recognised."""
	units = { "s" : 1, "m" : 60, "h" : 3600, "d" : 86400, "w" : 604800 }
	for unit, size in units.items():
		if value.endswith(unit):
			return int(value[:-len(unit)]) * size
	return int(value) * units[default]

def parse_bool(value):
	"""Parse a boolean value (0, 1, false or true). Raise ValueError if
	the value isn't recognised."""
	value = value.strip().lower()
	if value == "0" or value == "false":
		return 0
	elif value == "1" or value == "true":
		return 1
	else:
		raise ValueError("Bad boolean value: " + value)

def parse_list(value):
	"""Parse a list of keywords separated by whitespace."""
	return value.strip().split(None)

def parse_feed_args(argparams, arglines):
	"""Parse a list of feed arguments. Raise ConfigError if the syntax is invalid."""
	args = {}
	for a in argparams:
		as = a.split("=", 1)
		if len(as) != 2:
			raise ConfigError("Bad feed argument in config: " + a)
		args[as[0]] = as[1]
	for a in arglines:
		as = a.split(None, 1)
		if len(as) != 2:
			raise ConfigError("Bad argument line in config: " + a)
		args[as[0]] = as[1]
	if "maxage" in args:
		args["maxage"] = parse_time(args["maxage"])
	return args

class ConfigError(Exception): pass

class Config:
	"""The aggregator's configuration."""

	def __init__(self):
		self.files_loaded = []
		if have_threading:
			self.loglock = threading.Lock()
		self.reset()

	def reset(self):
		self.config = {
			"feedslist" : [],
			"feeddefaults" : {},
			"defines" : {},
			"outputfile" : "output.html",
			"maxarticles" : 200,
			"maxage" : 0,
			"expireage" : 24 * 60 * 60,
			"keepmin" : 0,
			"dayformat" : "%A, %d %B %Y",
			"timeformat" : "%I:%M %p",
			"datetimeformat" : None,
			"userefresh" : 0,
			"showfeeds" : 1,
			"timeout" : 30,
			"template" : "default",
			"itemtemplate" : "default",
			"verbose" : 0,
			"ignoretimeouts" : 0,
			"daysections" : 1,
			"timesections" : 1,
			"blocklevelhtml" : 1,
			"tidyhtml" : 0,
			"sortbyfeeddate" : 0,
			"currentonly" : 0,
			"hideduplicates" : "",
			"newfeedperiod" : "3h",
			"changeconfig": 0,
			"numthreads": 0,
			}

	def __getitem__(self, key): return self.config[key]
	def __setitem__(self, key, value): self.config[key] = value

	def reload(self):
		self.log("Reloading config files")
		self.reset()
		for filename in self.files_loaded:
			self.load(filename, False)

	def load(self, filename, explicitly_loaded = True):
		"""Load configuration from a config file."""
		if explicitly_loaded:
			self.files_loaded.append(filename)

		lines = []
		try:
			f = open(filename, "r")
			for line in f.xreadlines():
				stripped = line.strip()
				if stripped == "" or stripped[0] == "#":
					continue
				if line[0] in string.whitespace:
					if lines == []:
						raise ConfigError("First line in config cannot be an argument")
					lines[-1][1].append(stripped)
				else:
					lines.append((stripped, []))
			f.close()
		except IOError:
			raise ConfigError("Can't read config file: " + filename)

		for line, arglines in lines:
			try:
				self.load_line(line, arglines)
			except ValueError:
				raise ConfigError("Bad value in config: " + line)

	def load_line(self, line, arglines):
		"""Process a configuration directive."""

		l = line.split(None, 1)
		if len(l) == 1 and l[0] == "feeddefaults":
			l.append("")
		elif len(l) != 2:
			raise ConfigError("Bad line in config: " + line)

		handled_arglines = False
		if l[0] == "feed":
			l = l[1].split(None)
			if len(l) < 2:
				raise ConfigError("Bad line in config: " + line)
			self["feedslist"].append((l[1], parse_time(l[0]), parse_feed_args(l[2:], arglines)))
			handled_arglines = True
		elif l[0] == "feeddefaults":
			self["feeddefaults"] = parse_feed_args(l[1].split(None), arglines)
			handled_arglines = True
		elif l[0] == "define":
			l = l[1].split(None, 1)
			if len(l) != 2:
				raise ConfigError("Bad line in config: " + line)
			self["defines"][l[0]] = l[1]
		elif l[0] == "plugindirs":
			for dir in parse_list(l[1]):
				plugins.load_plugins(dir, self)
		elif l[0] == "outputfile":
			self["outputfile"] = l[1]
		elif l[0] == "maxarticles":
			self["maxarticles"] = int(l[1])
		elif l[0] == "maxage":
			self["maxage"] = parse_time(l[1])
		elif l[0] == "expireage":
			self["expireage"] = parse_time(l[1])
		elif l[0] == "keepmin":
			self["keepmin"] = int(l[1])
		elif l[0] == "dayformat":
			self["dayformat"] = l[1]
		elif l[0] == "timeformat":
			self["timeformat"] = l[1]
		elif l[0] == "datetimeformat":
			self["datetimeformat"] = l[1]
		elif l[0] == "userefresh":
			self["userefresh"] = parse_bool(l[1])
		elif l[0] == "showfeeds":
			self["showfeeds"] = parse_bool(l[1])
		elif l[0] == "timeout":
			self["timeout"] = parse_time(l[1], "s")
		elif l[0] == "template":
			self["template"] = l[1]
		elif l[0] == "itemtemplate":
			self["itemtemplate"] = l[1]
		elif l[0] == "verbose":
			self["verbose"] = parse_bool(l[1])
		elif l[0] == "ignoretimeouts":
			self["ignoretimeouts"] = parse_bool(l[1])
		elif l[0] == "daysections":
			self["daysections"] = parse_bool(l[1])
		elif l[0] == "timesections":
			self["timesections"] = parse_bool(l[1])
		elif l[0] == "blocklevelhtml":
			self["blocklevelhtml"] = parse_bool(l[1])
		elif l[0] == "tidyhtml":
			self["tidyhtml"] = parse_bool(l[1])
		elif l[0] == "sortbyfeeddate":
			self["sortbyfeeddate"] = parse_bool(l[1])
		elif l[0] == "currentonly":
			self["currentonly"] = parse_bool(l[1])
		elif l[0] == "hideduplicates":
			self["hideduplicates"] = parse_list(l[1])
		elif l[0] == "newfeedperiod":
			self["newfeedperiod"] = l[1]
		elif l[0] == "changeconfig":
			self["changeconfig"] = parse_bool(l[1])
		elif l[0] == "numthreads":
			self["numthreads"] = int(l[1])
		elif l[0] == "include":
			self.load(l[1], False)
		elif plugins.call_hook("config_option_arglines", self, l[0], l[1], arglines):
			handled_arglines = True
		elif plugins.call_hook("config_option", self, l[0], l[1]):
			pass
		else:
			raise ConfigError("Unknown config command: " + l[0])

		if arglines != [] and not handled_arglines:
			raise ConfigError("Bad argument lines in config after: " + line)

	def log(self, *args):
		"""If running in verbose mode, print a status message."""
		if self["verbose"]:
			if have_threading:
				self.loglock.acquire()
			print >>sys.stderr, "".join(map(str, args))
			if have_threading:
				self.loglock.release()

	def bug(self, *args):
		"""Report detection of a bug in rawdog."""
		print >>sys.stderr, "Internal error detected in rawdog:"
		print >>sys.stderr, "".join(map(str, args))
		print >>sys.stderr, "This could be caused by a bug in rawdog itself or in a plugin."
		print >>sys.stderr, "Please send this error message and your config file to the rawdog author."

def edit_file(filename, editfunc):
	"""Edit a file in place: for each line in the input file, call
	editfunc(line, outputfile), then rename the output file over the input
	file."""
	newname = "%s.new-%d" % (filename, os.getpid())
	oldfile = open(filename, "r")
	newfile = open(newname, "w")
	editfunc(oldfile, newfile)
	newfile.close()
	oldfile.close()
	os.rename(newname, filename)

class AddFeedEditor:
	def __init__(self, feedline):
		self.feedline = feedline
	def edit(self, inputfile, outputfile):
		d = inputfile.read()
		outputfile.write(d)
		if not d.endswith("\n"):
			outputfile.write("\n")
		outputfile.write(self.feedline)

def add_feed(filename, url, rawdog, config):
	"""Try to add a feed to the config file."""
	feeds = feedfinder.feeds(url)
	if feeds == []:
		print >>sys.stderr, "Cannot find any feeds in " + url
	else:
		feed = feeds[0]
		if feed in rawdog.feeds:
			print >>sys.stderr, "Feed " + feed + " is already in the config file"
		else:
			print >>sys.stderr, "Adding feed " + feed
			feedline = "feed %s %s\n" % (config["newfeedperiod"], feed)
			edit_file(filename, AddFeedEditor(feedline).edit)

class ChangeFeedEditor:
	def __init__(self, oldurl, newurl):
		self.oldurl = oldurl
		self.newurl = newurl
	def edit(self, inputfile, outputfile):
		for line in inputfile.xreadlines():
			ls = line.strip().split(None)
			if len(ls) > 2 and ls[0] == "feed" and ls[2] == self.oldurl:
				line = line.replace(self.oldurl, self.newurl, 1)
			outputfile.write(line)

class RemoveFeedEditor:
	def __init__(self, url):
		self.url = url
	def edit(self, inputfile, outputfile):
		while 1:
			l = inputfile.readline()
			if l == "":
				break
			ls = l.strip().split(None)
			if len(ls) > 2 and ls[0] == "feed" and ls[2] == self.url:
				while 1:
					l = inputfile.readline()
					if l == "":
						break
					elif l[0] == "#":
						outputfile.write(l)
					elif l[0] not in string.whitespace:
						outputfile.write(l)
						break
			else:
				outputfile.write(l)

def remove_feed(filename, url, config):
	"""Try to remove a feed from the config file."""
	if url not in [f[0] for f in config["feedslist"]]:
		print >>sys.stderr, "Feed " + url + " is not in the config file"
	else:
		print >>sys.stderr, "Removing feed " + url
		edit_file(filename, RemoveFeedEditor(url).edit)

class FeedFetcher:
	"""Class that will handle fetching a set of feeds in parallel."""

	def __init__(self, rawdog, feedlist, config):
		self.rawdog = rawdog
		self.config = config
		self.lock = threading.Lock()
		self.jobs = {}
		for feed in feedlist:
			self.jobs[feed] = 1
		self.results = {}

	def worker(self, num):
		rawdog = self.rawdog
		config = self.config

		config.log("Thread ", num, " starting")
		while 1:
			self.lock.acquire()
			if self.jobs == {}:
				job = None
			else:
				job = self.jobs.keys()[0]
				del self.jobs[job]
			self.lock.release()
			if job is None:
				break

			config.log("Thread ", num, " fetching feed: ", job)
			feed = rawdog.feeds[job]
			plugins.call_hook("pre_update_feed", rawdog, config, feed)
			self.results[job] = feed.fetch(rawdog, config)
		config.log("Thread ", num, " done")

	def run(self, numworkers):
		self.config.log("Thread farm starting with ", len(self.jobs), " jobs")
		workers = []
		for i in range(numworkers):
			self.lock.acquire()
			isempty = (self.jobs == {})
			self.lock.release()
			if isempty:
				# No jobs left in the queue -- don't bother
				# starting any more workers.
				break

			t = threading.Thread(target = self.worker, args = (i,))
			t.start()
			workers.append(t)
		for worker in workers:
			worker.join()
		self.config.log("Thread farm finished with ", len(self.results), " results")
		return self.results

class Rawdog(Persistable):
	"""The aggregator itself."""

	def __init__(self):
		self.feeds = {}
		self.articles = {}
		self.plugin_storage = {}
		self.state_version = STATE_VERSION

	def get_plugin_storage(self, plugin):
		try:
			st = self.plugin_storage.setdefault(plugin, {})
		except AttributeError:
			# rawdog before 2.5 didn't have plugin storage.
			st = {}
			self.plugin_storage = {plugin: st}
		return st

	def check_state_version(self):
		"""Check the version of the state file."""
		try:
			version = self.state_version
		except AttributeError:
			# rawdog 1.x didn't keep track of this.
			version = 1
		return version == STATE_VERSION

	def change_feed_url(self, oldurl, newurl):
		"""Change the URL of a feed."""

		assert self.feeds.has_key(oldurl)
		if self.feeds.has_key(newurl):
			print >>sys.stderr, "Error: New feed URL is already subscribed; please remove the old one"
			print >>sys.stderr, "from the config file by hand."
			return

		edit_file("config", ChangeFeedEditor(oldurl, newurl).edit)

		feed = self.feeds[oldurl]
		feed.url = newurl
		del self.feeds[oldurl]
		self.feeds[newurl] = feed

		for article in self.articles.values():
			if article.feed == oldurl:
				article.feed = newurl

		print >>sys.stderr, "Feed URL automatically changed."

	def list(self, config):
		"""List the configured feeds."""
		for url, feed in self.feeds.items():
			feed_info = feed.feed_info
			print url
			print "  ID:", feed.get_id(config)
			print "  Hash:", short_hash(url)
			print "  Title:", feed.get_html_name(config)
			print "  Link:", feed_info.get("link")

	def sync_from_config(self, config):
		"""Update rawdog's internal state to match the
		configuration."""
		seenfeeds = {}
		for (url, period, args) in config["feedslist"]:
			seenfeeds[url] = 1
			if not self.feeds.has_key(url):
				config.log("Adding new feed: ", url)
				self.feeds[url] = Feed(url)
				self.modified()
			feed = self.feeds[url]
			if feed.period != period:
				config.log("Changed feed period: ", url)
				feed.period = period
				self.modified()
			newargs = {}
			newargs.update(config["feeddefaults"])
			newargs.update(args)
			if feed.args != newargs:
				config.log("Changed feed options: ", url)
				feed.args = newargs
				self.modified()
		for url in self.feeds.keys():
			if not seenfeeds.has_key(url):
				config.log("Removing feed: ", url)
				del self.feeds[url]
				for key, article in self.articles.items():
					if article.feed == url:
						del self.articles[key]
				self.modified()

	def update(self, config, feedurl = None):
		"""Perform the update action: check feeds for new articles, and
		expire old ones."""
		config.log("Starting update")
		timeoffsetseconds = 0
		if config["defines"].has_key("timeoffset"):
			timeoffsetseconds = parse_time(config["defines"]["timeoffset"])
		now = time.time() + timeoffsetseconds

		feedparser._FeedParserMixin.can_contain_relative_uris = ["url"]
		feedparser._FeedParserMixin.can_contain_dangerous_markup = []
		set_socket_timeout(config["timeout"])

		if feedurl is None:
			update_feeds = [url for url in self.feeds.keys()
			                    if self.feeds[url].needs_update(now)]
		elif self.feeds.has_key(feedurl):
			update_feeds = [feedurl]
			self.feeds[feedurl].etag = None
			self.feeds[feedurl].modified = None
		else:
			print "No such feed: " + feedurl
			update_feeds = []

		numfeeds = len(update_feeds)
		config.log("Will update ", numfeeds, " feeds")

		if have_threading and config["numthreads"] > 0:
			fetcher = FeedFetcher(self, update_feeds, config)
			prefetched = fetcher.run(config["numthreads"])
		else:
			prefetched = {}

		count = 0
		seen_some_items = {}
		for url in update_feeds:
			count += 1
			config.log("Updating feed ", count, " of " , numfeeds, ": ", url)
			feed = self.feeds[url]
			if url in prefetched:
				content = prefetched[url]
			else:
				plugins.call_hook("pre_update_feed", self, config, feed)
				content = feed.fetch(self, config)
			plugins.call_hook("mid_update_feed", self, config, feed, content)
			rc = feed.update(self, now, config, content)
			plugins.call_hook("post_update_feed", self, config, feed, rc)
			if rc:
				seen_some_items[url] = 1

		expiry_list = []
		feedcounts = {}
		for key, article in self.articles.items():
			url = article.feed
			feedcounts[url] = feedcounts.get(url, 0) + 1
			expiry_list.append((article.added, article.sequence, key, article))
		expiry_list.sort()

		count = 0
		for date, seq, key, article in expiry_list:
			url = article.feed
			if (seen_some_items.has_key(url)
			    and self.feeds.has_key(url)
			    and article.can_expire(now, config)
			    and feedcounts[url] > self.feeds[url].get_keepmin(config)):
				plugins.call_hook("article_expired", self, config, article, now)
				count += 1
				feedcounts[url] -= 1
				del self.articles[key]
		config.log("Expired ", count, " articles, leaving ", len(self.articles))

		self.modified()
		config.log("Finished update")

	def get_template(self, config):
		"""Get the main template."""
		if config["template"] != "default":
			return load_file(config["template"])

		template = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN"
   "http://www.w3.org/TR/html4/strict.dtd">
<html lang="en">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=ISO-8859-1">
    <meta name="robots" content="noindex,nofollow,noarchive">
"""
		if config["userefresh"]:
			template += """__refresh__
"""
		template += """    <link rel="stylesheet" href="style.css" type="text/css">
    <title>rawdog</title>
</head>
<body id="rawdog">
<div id="header">
<h1>rawdog</h1>
</div>
<div id="items">
__items__
</div>
"""
		if config["showfeeds"]:
			template += """<h2 id="feedstatsheader">Feeds</h2>
<div id="feedstats">
__feeds__
</div>
"""
		template += """<div id="footer">
<p id="aboutrawdog">Generated by
<a href="http://offog.org/code/rawdog.html">rawdog</a>
version __version__
by <a href="mailto:ats@offog.org">Adam Sampson</a>.</p>
</div>
</body>
</html>
"""
		return template

	def get_itemtemplate(self, config):
		"""Get the item template."""
		if config["itemtemplate"] != "default":
			return load_file(config["itemtemplate"])

		template = """<div class="item feed-__feed_hash__ feed-__feed_id__" id="item-__hash__">
<p class="itemheader">
<span class="itemtitle">__title__</span>
<span class="itemfrom">[__feed_title__]</span>
</p>
__if_description__<div class="itemdescription">
__description__
</div>__endif__
</div>

"""
		return template

	def show_template(self, config):
		"""Show the configured main template."""
		print self.get_template(config)

	def show_itemtemplate(self, config):
		"""Show the configured item template."""
		print self.get_itemtemplate(config)

	def write_article(self, f, article, config):
		"""Write an article to the given file."""
		feed = self.feeds[article.feed]
		feed_info = feed.feed_info
		entry_info = article.entry_info

		link = entry_info.get("link")
		if link == "":
			link = None

		guid = entry_info.get("id")
		if guid == "":
			guid = None

		itembits = {}
		for name, value in feed.args.items():
			if name.startswith("define_"):
				itembits[name[7:]] = value

		title = detail_to_html(entry_info.get("title_detail"), True, config)

		key = None
		for k in ["content", "summary_detail"]:
			if entry_info.has_key(k):
				key = k
				break
		if key is None:
			description = None
		else:
			force_preformatted = feed.args.has_key("format") and (feed.args["format"] == "text")
			description = detail_to_html(entry_info[key], False, config, force_preformatted)

		date = article.date
		if title is None:
			if link is None:
				title = "Article"
			else:
				title = "Link"

		itembits["title_no_link"] = title
		if link is not None:
			itembits["url"] = string_to_html(link, config)
		else:
			itembits["url"] = ""
		if guid is not None:
			itembits["guid"] = string_to_html(guid, config)
		else:
			itembits["guid"] = ""
		if link is None:
			itembits["title"] = title
		else:
			itembits["title"] = '<a href="' + string_to_html(link, config) + '">' + title + '</a>'

		itembits["feed_title_no_link"] = detail_to_html(feed_info.get("title_detail"), True, config)
		itembits["feed_title"] = feed.get_html_link(config)
		itembits["feed_url"] = string_to_html(feed.url, config)
		itembits["feed_hash"] = short_hash(feed.url)
		itembits["feed_id"] = feed.get_id(config)
		itembits["hash"] = short_hash(article.hash)

		if description is not None:
			itembits["description"] = description
		else:
			itembits["description"] = ""

		author = author_to_html(entry_info, feed.url, config)
		if author is not None:
			itembits["author"] = author
		else:
			itembits["author"] = ""

		author_name = entry_info.get("author_detail")["name"];
		if author_name is not None:
			itembits["author_name"] = author_name
		else:
			itembits["author_name"] = ""
		author_email = entry_info.get("author_detail")["email"];
		if author_email is not None:
			itembits["author_email"] = author_email
		else:
			itembits["author_email"] = ""
		author_url = entry_info.get("author_detail")["url"];
		if author_url is not None:
			itembits["author_url"] = author_url
		else:
			itembits["author_url"] = ""

		itembits["added"] = format_time(article.added, config)
		if date is not None:
			itembits["date"] = format_time(date, config)
		else:
			itembits["date"] = ""

		plugins.call_hook("output_item_bits", self, config, feed, article, itembits)
		itemtemplate = self.get_itemtemplate(config)
		f.write(fill_template(itemtemplate, itembits))

	def write_remove_dups(self, articles, config, now):
		"""Filter the list of articles to remove articles that are too
		old or are duplicates."""
		kept_articles = []
		seen_links = {}
		seen_guids = {}
		dup_count = 0
		for article in articles:
			feed = self.feeds[article.feed]
			age = now - article.added

			maxage = config["maxage"]
			if "maxage" in feed.args:
				maxage = feed.args["maxage"]
			if maxage != 0 and age > maxage:
				continue

			entry_info = article.entry_info

			link = entry_info.get("link")
			if link == "":
				link = None

			guid = entry_info.get("id")
			if guid == "":
				guid = None

			if feed.args.get("allowduplicates") != "true":
				is_dup = False
				for key in config["hideduplicates"]:
					if key == "id" and guid is not None:
						if seen_guids.has_key(guid):
							is_dup = True
						seen_guids[guid] = 1
						break
					elif key == "link" and link is not None:
						if seen_links.has_key(link):
							is_dup = True
						seen_links[link] = 1
						break
				if is_dup:
					dup_count += 1
					continue

			kept_articles.append(article)
		return (kept_articles, dup_count)

	def get_main_template_bits(self, config):
		"""Get the bits that are used in the default main template,
		with the exception of items and num_items."""
		bits = { "version" : VERSION }
		bits.update(config["defines"])

		refresh = config["expireage"]
		for feed in self.feeds.values():
			if feed.period < refresh: refresh = feed.period

		bits["refresh"] = """<meta http-equiv="Refresh" """ + 'content="' + str(refresh) + '"' + """>"""

		f = StringIO()
		print >>f, """<table id="feeds">
<tr id="feedsheader">
<th>Feed</th><th>RSS</th><th>Last fetched</th><th>Next fetched after</th>
</tr>"""
		feeds = self.feeds.values()
		feeds.sort(lambda a, b: cmp(a.get_html_name(config).lower(), b.get_html_name(config).lower()))
		feeditems = ""
		for feed in feeds:
			feeditembits = { "version" : VERSION }
			feeditembits["feed_title"] = feed.get_html_link(config)
			feeditembits["feed_title_no_link"] = detail_to_html(feed.feed_info.get("title_detail"), True, config)
			feeditembits["feed_url"] = cgi.escape(feed.url)
			feeditembits["last_update"] = format_time(feed.last_update, config)
			feeditembits["next_update"] = format_time(feed.last_update + feed.period, config)
			feeditembits["feed_id"] = feed.get_id(config)
			for name, value in feed.args.items():
				if name.startswith("define_"):
					feeditembits[name[7:]] = value
			print >>f, '<tr class="feedsrow">'
			print >>f, '<td>' + feeditembits["feed_title"] + '</td>'
			print >>f, '<td><a class="xmlbutton" href="' + feeditembits["feed_url"] + '">XML</a></td>'
			print >>f, '<td>' + feeditembits["last_update"] + '</td>'
			print >>f, '<td>' + feeditembits["next_update"] + '</td>'
			print >>f, '</tr>'
			if config["defines"].has_key("feeditemtemplate"):
				feeditems += fill_template(load_file(config["defines"]["feeditemtemplate"]), feeditembits)
		print >>f, """</table>"""
		bits["feeds"] = f.getvalue()
		bits["feeditems"] = feeditems

		bits["num_feeds"] = str(len(feeds))

		return bits

	def write_output_file(self, articles, article_dates, config):
		"""Write a regular rawdog HTML output file."""
		f = StringIO()
		dw = DayWriter(f, config)
		plugins.call_hook("output_items_begin", self, config, f)

		for article in articles:
			if not plugins.call_hook("output_items_heading", self, config, f, article, article_dates[article]):
				dw.time(article_dates[article])

			self.write_article(f, article, config)

		dw.close()
		plugins.call_hook("output_items_end", self, config, f)

		bits = self.get_main_template_bits(config)
		bits["items"] = f.getvalue()
		bits["num_items"] = str(len(self.articles))
		plugins.call_hook("output_bits", self, config, bits)
		s = fill_template(self.get_template(config), bits)
		outputfile = config["outputfile"]
		if outputfile == "-":
			write_ascii(sys.stdout, s, config)
		else:
			config.log("Writing output file: ", outputfile)
			f = open(outputfile + ".new", "w")
			write_ascii(f, s, config)
			f.close()
			os.rename(outputfile + ".new", outputfile)

	def write(self, config):
		"""Perform the write action: write articles to the output
		file."""
		config.log("Starting write")
		timeoffsetseconds = 0
		if config["defines"].has_key("timeoffset"):
			timeoffsetseconds = parse_time(config["defines"]["timeoffset"])
		now = time.time() + timeoffsetseconds

		article_dates = {}
		articles = self.articles.values()
		for a in articles:
			if config["sortbyfeeddate"]:
				article_dates[a] = a.date or a.added
			else:
				article_dates[a] = a.added
		numarticles = len(articles)

		def compare(a, b):
			"""Compare two articles to decide how they
			   should be sorted. Sort by added date, then
			   by feed, then by sequence, then by hash."""
			i = cmp(article_dates[b], article_dates[a])
			if i != 0:
				return i
			i = cmp(a.feed, b.feed)
			if i != 0:
				return i
			i = cmp(a.sequence, b.sequence)
			if i != 0:
				return i
			return cmp(a.hash, b.hash)
		plugins.call_hook("output_filter", self, config, articles)
		articles.sort(compare)
		plugins.call_hook("output_sort", self, config, articles)

		if config["maxarticles"] != 0:
			articles = articles[:config["maxarticles"]]

		plugins.call_hook("output_write", self, config, articles)

		if not plugins.call_hook("output_sorted_filter", self, config, articles):
			(articles, dup_count) = self.write_remove_dups(articles, config, now)
		else:
			dup_count = 0

		config.log("Selected ", len(articles), " of ", numarticles, " articles to write; ignored ", dup_count, " duplicates")

		if not plugins.call_hook("output_write_files", self, config, articles, article_dates):
			self.write_output_file(articles, article_dates, config)

		config.log("Finished write")

def usage():
	"""Display usage information."""
	print """rawdog, version """ + VERSION + """
Usage: rawdog [OPTION]...

General options (use only once):
-d|--dir DIR                 Use DIR instead of ~/.rawdog
-v, --verbose                Print more detailed status information
-N, --no-locking             Do not lock the state file
-W, --no-lock-wait           Exit silently if state file is locked
--help                       Display this help and exit

Actions (performed in order given):
-u, --update                 Fetch data from feeds and store it
-l, --list                   List feeds known at time of last update
-w, --write                  Write out HTML output
-f|--update-feed URL         Force an update on the single feed URL
-c|--config FILE             Read additional config file FILE
-t, --show-template          Print the template currently in use
-T, --show-itemtemplate      Print the item template currently in use
-a|--add URL                 Try to find a feed associated with URL and
                             add it to the config file
-r|--remove URL              Remove feed URL from the config file

Special actions (all other options are ignored if one of these is specified):
--upgrade OLDDIR NEWDIR      Import feed state from rawdog 1.x directory
                             OLDDIR into rawdog 2.x directory NEWDIR

Report bugs to <ats@offog.org>."""

def main(argv):
	"""The command-line interface to the aggregator."""

	locale.setlocale(locale.LC_ALL, "")

	try:
		(optlist, args) = getopt.getopt(argv, "ulwf:c:tTd:va:r:NW", ["update", "list", "write", "update-feed=", "help", "config=", "show-template", "dir=", "show-itemtemplate", "verbose", "upgrade", "add=", "remove=", "no-locking", "no-lock-wait"])
	except getopt.GetoptError, s:
		print s
		usage()
		return 1

	for o, a in optlist:
		if o == "--upgrade" and len(args) == 2:
			import upgrade_1_2
			return upgrade_1_2.upgrade(args[0], args[1])

	if len(args) != 0:
		usage()
		return 1

	if "HOME" in os.environ:
		statedir = os.environ["HOME"] + "/.rawdog"
	else:
		statedir = None
	verbose = 0
	locking = 1
	no_lock_wait = 0
	for o, a in optlist:
		if o == "--help":
			usage()
			return 0
		elif o in ("-d", "--dir"):
			statedir = a
		elif o in ("-v", "--verbose"):
			verbose = 1
		elif o in ("-N", "--no-locking"):
			locking = 0
		elif o in ("-W", "--no-lock-wait"):
			no_lock_wait = 1
	if statedir is None:
		print "$HOME not set and state dir not explicitly specified; please use -d/--dir"
		return 1

	try:
		os.chdir(statedir)
	except OSError:
		print "No " + statedir + " directory"
		return 1

	sys.path.append(".")

	config = Config()
	try:
		config.load("config")
	except ConfigError, err:
		print >>sys.stderr, "In config:"
		print >>sys.stderr, err
		return 1
	if verbose:
		config["verbose"] = True

	persister = Persister("state", Rawdog, locking)
	try:
		rawdog = persister.load(no_block = no_lock_wait)
		if rawdog is None:
			return 0
	except KeyboardInterrupt:
		return 1
	except:
		print "An error occurred while reading state from " + statedir + "/state."
		print "This usually means the file is corrupt, and removing it will fix the problem."
		return 1

	if not rawdog.check_state_version():
		print "The state file " + statedir + "/state was created by an older"
		print "version of rawdog, and cannot be read by this version."
		print "Removing the state file will fix it."
		return 1

	rawdog.sync_from_config(config)

	plugins.call_hook("startup", rawdog, config)

	for o, a in optlist:
		if o in ("-u", "--update"):
			rawdog.update(config)
		elif o in ("-f", "--update-feed"):
			rawdog.update(config, a)
		elif o in ("-l", "--list"):
			rawdog.list(config)
		elif o in ("-w", "--write"):
			rawdog.write(config)
		elif o in ("-c", "--config"):
			try:
				config.load(a)
			except ConfigError, err:
				print >>sys.stderr, "In " + a + ":"
				print >>sys.stderr, err
				return 1
		elif o in ("-t", "--show-template"):
			rawdog.show_template(config)
		elif o in ("-T", "--show-itemtemplate"):
			rawdog.show_itemtemplate(config)
		elif o in ("-a", "--add"):
			add_feed("config", a, rawdog, config)
			config.reload()
			rawdog.sync_from_config(config)
		elif o in ("-r", "--remove"):
			remove_feed("config", a, config)
			config.reload()
			rawdog.sync_from_config(config)

	plugins.call_hook("shutdown", rawdog, config)

	persister.save()

	return 0

