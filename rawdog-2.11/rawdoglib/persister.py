# persister: safe class persistance wrapper
# Copyright 2003, 2004, 2005 Adam Sampson <ats@offog.org>
#
# persister is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation; either version 2.1 of the
# License, or (at your option) any later version.
#
# persister is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with persister; see the file COPYING.LGPL. If not,
# write to the Free Software Foundation, Inc., 51 Franklin Street,
# Fifth Floor, Boston, MA 02110-1301, USA, or see http://www.gnu.org/.

import fcntl, os, errno
import cPickle as pickle

class Persistable:
	"""Something which can be persisted. When a subclass of this wants to
	   indicate that it has been modified, it should call
	   self.modified()."""
	def __init__(self): self._modified = False
	def modified(self, state = True): self._modified = state
	def is_modified(self): return self._modified

class Persister:
	"""Persist another class to a file, safely. The class being persisted
	   must derive from Persistable (although this isn't enforced)."""

	def __init__(self, filename, klass, use_locking = True):
		self.filename = filename
		self.klass = klass
		self.use_locking = use_locking
		self.file = None
		self.object = None

	def load(self, no_block = True):
		"""Load the persisted object from the file, or create a new one
		   if this isn't possible. Returns the loaded object."""

		def get_lock():
			if not self.use_locking:
				return True
			mode = fcntl.LOCK_EX
			if no_block:
				mode |= fcntl.LOCK_NB
			try:
				fcntl.lockf(self.file.fileno(), mode)
			except IOError, e:
				if no_block and e.errno in (errno.EACCES, errno.EAGAIN):
					return False
				raise e
			return True

		try:
			self.file = open(self.filename, "r+")
			if not get_lock():
				return None
			self.object = pickle.load(self.file)
			self.object.modified(False)
		except IOError:
			self.file = open(self.filename, "w+")
			if not get_lock():
				return None
			self.object = self.klass()
			self.object.modified()
		return self.object

	def save(self):
		"""Save the persisted object back to the file if necessary."""
		if self.object.is_modified():
			newname = "%s.new-%d" % (self.filename, os.getpid())
			newfile = open(newname, "w")
			try:
				pickle.dump(self.object, newfile, pickle.HIGHEST_PROTOCOL)
			except AttributeError:
				# Python 2.2 doesn't have the protocol
				# argument.
				pickle.dump(self.object, newfile, True)
			newfile.close()
			os.rename(newname, self.filename)
		self.file.close()

