#!/usr/bin/env python

import sys
import os

sys.path.append(os.path.expandvars("$GIP_LOCATION/lib/python"))
from gip_common import config, getLogger, getTemplate, printTemplate
from gip_site import generateGlueSite

log = getLogger("GIP.Site")

def print_site(cp):
    info = generateGlueSite(cp)
    siteTemplate = getTemplate("GlueSite", "GlueSiteUniqueID")
    printTemplate(siteTemplate, info)

def main():
    try:
        cp = config()
        print_site(cp)
    except Exception, e:
        sys.stdout = sys.stderr
        log.error(e)
        raise

if __name__ == '__main__':
    main()
