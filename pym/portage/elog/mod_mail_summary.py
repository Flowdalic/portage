# elog/mod_mail_summary.py - elog dispatch module
# Copyright 2006-2007 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2
# $Id$

import portage.mail, socket, os, time
from portage.exception import PortageException
from email.MIMEText import MIMEText as TextMessage

_items = {}
def process(mysettings, key, logentries, fulltext):
	global _items
	header = ">>> Messages generated for package %s by process %d on %s:\n\n" % \
		(key, os.getpid(), time.strftime("%Y%m%d-%H%M%S", time.gmtime(time.time())))
	config_root = mysettings["PORTAGE_CONFIGROOT"]
	mysettings, items = _items.setdefault(config_root, (mysettings, {}))
	items[key] = header + fulltext

def finalize(mysettings=None):
	"""The mysettings parameter is just for backward compatibility since
	an older version of portage will import the module from a newer version
	when it upgrades itself."""
	global _items
	for mysettings, items in _items.itervalues():
		_finalize(mysettings, items)
	_items.clear()

def _finalize(mysettings, items):
	if len(items) == 0:
		return
	elif len(items) == 1:
		count = "one package"
	else:
		count = "multiple packages"
	if mysettings.has_key("PORTAGE_ELOG_MAILURI"):
		myrecipient = mysettings["PORTAGE_ELOG_MAILURI"].split()[0]
	else:
		myrecipient = "root@localhost"
	
	myfrom = mysettings["PORTAGE_ELOG_MAILFROM"]
	mysubject = mysettings["PORTAGE_ELOG_MAILSUBJECT"]
	mysubject = mysubject.replace("${PACKAGE}", count)
	mysubject = mysubject.replace("${HOST}", socket.getfqdn())

	mybody = "elog messages for the following packages generated by " + \
		"process %d on host %s:\n" % (os.getpid(), socket.getfqdn())
	for key in items:
		 mybody += "- %s\n" % key

	mymessage = portage.mail.create_message(myfrom, myrecipient, mysubject,
		mybody, attachments=items.values())
	try:
		portage.mail.send_mail(mysettings, mymessage)
	except PortageException, e:
		print str(e)

	return
