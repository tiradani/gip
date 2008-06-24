
"""
Common function which provide information about the Condor batch system.

This module interacts with condor through the following commands:
   * condor_q
   * condor_status

It takes advantage of the XML format of the ClassAds in order to make parsing
easier.
"""

from xml.sax import make_parser
from xml.sax.handler import ContentHandler, feature_external_ges

from gip_common import voList, cp_getBoolean, getLogger
from gip_testing import runCommand

condor_version = "condor_version"
condor_group = "condor_config_val GROUP_NAMES"
condor_quota = "condor_config_val GROUP_QUOTA_group_%(group)s"
condor_prio = "condor_config_val GROUP_PRIO_FACTOR_group_%(group)s"
condor_status = "condor_status -xml"
condor_job_status = "condor_status -submitter -xml"

log = getLogger("GIP.Condor")

class ClassAdParser(ContentHandler):
    """
    Streaming SAX handler for the output of condor_* -xml calls; it's around
    60 times faster and has a similar reduction in required memory.

    Use this as a ContentHandler for a SAX parser; call getJobInfo afterward
    to get the information about each job.
    
    getJobInfo returns a dictionary of jobs; the key for the dictionary is the
    Condor attribute passed in as 'idx' to the constructor; the value is another
    dictionary of key-value pairs from the condor JDL, where the keys is in
    the attribute list passed to the constructor.
    """

    def __init__(self, idx, attrlist=[]):
        """
        @param idx: The attribute name used to index the classads with.
        @keyword attrlist: A list of attributes to record; if it is empty, then
           parse all attributes.
        """
        self.attrlist = list(attrlist)
        if self.attrlist and idx not in self.attrlist:
            self.attrlist.append(idx)
        self.idxAttr = idx

    def startDocument(self):
        """
        Start up a parsing sequence; initialize myself.
        """
        self.attrInfo = ''
        self.caInfo = {}
    
    def startElement(self, name, attrs):
        """
        Open an XML element - take note if its a 'c', for the start of a new
        classad, or an 'a', the start of a new attribute.
        """
        if name == 'c':
            self.curCaInfo = {}
        elif name == 'a':
            self.attrName = str(attrs.get('n', 'Unknown'))
            self.attrInfo = ''
        else:
            pass

    def endElement(self, name):
        """
        End of an XML element - save everything we learned
        """
        if name == 'c':
            idx = self.curCaInfo.get(self.idxAttr, None)
            if idx:
                self.caInfo[idx] = self.curCaInfo
        elif name == 'a':
            if self.attrName in self.attrlist or len(self.attrlist) == 0:
                self.curCaInfo[self.attrName] = self.attrInfo
        else:
            pass

    def characters(self, ch):
        """
        Save up the XML characters found in the attribute.
        """
        self.attrInfo += str(ch)

    def getClassAds(self):
        """
        Returns a dictionary of dictionaries consisting of all the classAds
        and their attributes.
        """
        return self.caInfo

def parseCondorXml(fp, handler):
    """
    Parse XML from Condor.

    Create a SAX parser with the content handler B{handler}, then parse the
    contents of B{fp} with it.

    @param fp: A file-like object of the Condor XML data
    @param handler: An object which will be our content handler.
    @type handler: xml.sax.handler.ContentHandler
    @returns: None
    """
    parser = make_parser()
    parser.setContentHandler(handler)
    parser.setFeature(feature_external_ges, False)
    parser.parse(fp)

def condorCommand(command, cp, info={}):
    """
    Execute a command in the shell.  Returns a file-like object
    containing the stdout of the command

    Use this function instead of executing directly (os.popen); this will
    allow you to hook your providers into the testing framework.

    @param command: The command to execute
    @param cp: The GIP configuration object
    @keyword info: A dictionary-like object for Python string substitution
    @returns: a file-like object.
    """

    # must test for empty dict for special cases like the condor_status
    #  command which has -format '%s' arguments.  Python will try to do
    #  the string substitutions regardless of single quotes
    if info:
        cmd = command % info
    else:
        cmd = command

    return runCommand(cmd)

def getLrmsInfo(cp):
    """
    Get information from the LRMS (batch system).

    Returns the version of the condor client on your system.

    @returns: The condor version
    @rtype: string
    """
    for line in condorCommand(condor_version, cp):
        if line.startswith("$CondorVersion:"):
            return line[15:].strip()
    ve = ValueError("Bad output from condor_version.")
    log.exception(ve)
    raise ve

def getGroupInfo(vo_map, cp):
    """
    Get the group info from condor

    The return value is a dictionary; the key is the vo name, the values are
    another dictionary of the form {'quota': integer, 'prio': integer}

    @param vo_map: VoMapper object
    @param cp: A ConfigParse object with the GIP config information
    @returns: A dictionary whose keys are VO groups and values are the quota
        and priority of the group.
    """
    output = condorCommand(condor_group, cp).read().split(',')
    retval = {}
    if (not (output[0].strip().startswith('Not defined'))) and \
            (len(output[0].strip()) > 0):
        for group in output:
            group = group.strip()
            quota = condorCommand(condor_quota, cp, \
                {'group': group}).read().strip()
            prio = condorCommand(condor_prio, cp, \
                {'group': group}).read().strip()
            vo = vo_map[group]
            curInfo = retval.get(vo, {'quota': 0, 'prio': 0})
            try:
                curInfo['quota'] += int(quota)
            except:
                pass
            try:
                curInfo['prio'] += int(prio)
            except:
                pass
            retval[vo] = curInfo
    return retval

def getJobsInfo(vo_map, cp):
    """
    Retrieve information about the jobs in the Condor system.

    Query condor about the submitter status.  The returned job information is
    a dictionary whose keys are the VO name of the submitting user and values
    the aggregate information about that VO's activities.  The information is
    another dictionary showing the running, idle, held, and max_running jobs
    for that VO.

    @param vo_map: A vo_map object mapping users to VOs
    @param cp: A ConfigParser object with the GIP config information.
    @returns: A dictionary containing job information.
    """
    vo_jobs = {}
    fp = condorCommand(condor_job_status, cp)
    handler = ClassAdParser('Name', ['RunningJobs', 'IdleJobs', 'HeldJobs', \
        'MaxJobsRunning'])
    parseCondorXml(fp, handler)
    def addIntInfo(my_info_dict, classad_dict, my_key, classad_key):
        if my_key not in my_info_dict or classad_key not in classad_dict:
            return
        try:
            new_info = int(classad_dict[classad_key])
        except:
            pass
        my_info_dict[my_key] += new_info

    for user, info in handler.getClassAds().items():
        # Determine the VO, or skip the entry
        name = user.split("@")[0]
        try:
            vo = vo_map[name].lower()
        except Exception, e:
            log.exception(e)
            continue

        # Add the information to the current dictionary.
        my_info = vo_jobs.get(vo, {"running":0, "idle":0, "held":0, \
            'max_running':0})
        addIntInfo(my_info, info, "running", "RunningJobs")
        addIntInfo(my_info, info, "idle", "IdleJobs")
        addIntInfo(my_info, info, "held", "HeldJobs")
        addIntInfo(my_info, info, "max_running", "MaxJobsRunning")
        vo_jobs[vo] = my_info
    return vo_jobs

def parseNodes(cp):
    """
    Parse the condor nodes.

    @param cp: ConfigParser object for the GIP
    @returns: A tuple consisting of the total, claimed, and unclaimed nodes.
    """
    subtract = cp_getBoolean(cp, "condor", "subtract_owner", True)
    fp = condorCommand(condor_status, cp)
    handler = ClassAdParser('Name', ['State'])
    parseCondorXml(fp, handler)
    total = 0
    claimed = 0
    unclaimed = 0
    for machine, info in handler.getClassAds().items():
        total += 1
        if 'State' not in info:
            continue
        if info['State'] == 'Claimed':
            claimed += 1
        elif info['State'] == 'Unclaimed':
            unclaimed += 1
        elif subtract and info['State'] == 'Owner':
            total -= 1
    return total, claimed, unclaimed

