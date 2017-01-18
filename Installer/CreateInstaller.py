#!/usr/bin/python

import os
import subprocess
import argparse
import json
import shutil
import urllib


##
## Parse the command-line arguments
##

parser = argparse.ArgumentParser(description = 'Create the Osimis installer.')
parser.add_argument('--config', 
                    default = None,
                    help = 'Config of the build')
parser.add_argument('--target', 
                    default = '/tmp/OsimisInstaller',
                    help = 'Working directory')
parser.add_argument('--force', help = 'Reuse the working directory if it already exists',
                    action = 'store_true')

args = parser.parse_args()


##
## Load and validate the configuration
##

if args.config == None:
    print('Please provide a configuration file')
    exit(-1)

with open(args.config, 'r') as f:
    CONFIG = json.loads(f.read())

ARCHITECTURE = CONFIG['Architecture']

if not ARCHITECTURE in [ 32, 64 ]:
    print('ERROR- The "Architecture" option must be set to 32 or 64')
    exit(-1)


##
## Prepare the working directory
##

SOURCE = os.path.normpath(os.path.dirname(__file__))
TARGET = args.target

try:
    os.makedirs(TARGET)
except:
    if args.force:
        print('Reusing the target directory "%s"' % TARGET)
    else:
        print('ERROR- Please remove directory "%s" or add the "--force" flag' % TARGET)
        exit(-1)

def SafeMakedirs(path):
    try:
        os.makedirs(os.path.join(TARGET, path))
    except:
        pass

def CheckNotExisting(path):
    if os.path.exists(path) and not args.force:
        print('ERROR- Two distinct files with the same name exist: %s' % path)
        exit(-1)


SafeMakedirs('Artifacts')
SafeMakedirs('Configuration')
SafeMakedirs('Downloads')
SafeMakedirs('Resources')

for resource in os.listdir(os.path.join(SOURCE, 'Resources')):
    source = os.path.join(SOURCE, 'Resources', resource)
    target = os.path.join(TARGET, 'Resources', resource)

    if os.path.isfile(source):
        CheckNotExisting(target)
        shutil.copy(source, target);


##
## Download the build artifacts from the CIS
##

def Download(url, target):
    print ('Downloading: %s' % url)
    f = urllib.urlopen(url)
    if f.getcode() != 200:
        raise Exception('Cannot download: %s' % url)
    
    with open(target, 'wb') as g:
        g.write(f.read())
    
for component in CONFIG['Components']:
    if 'Artifacts' in component:
        for artifact in component['Artifacts']:
            target = os.path.join(TARGET, 'Artifacts', os.path.basename(artifact[0]))
            CheckNotExisting(target)

            if not os.path.exists(target):
                Download('%s/%s' % (CONFIG['CIS'], artifact[0]), target)

                
##
## Download additional resources
##

def GetDownloadBasename(f):
    return os.path.basename(f).split('?')[0]

for component in CONFIG['Components']:
    if 'Downloads' in component:
        for download in component['Downloads']:
            target = os.path.join(TARGET, 'Downloads', GetDownloadBasename(download[0]))
            CheckNotExisting(target)

            if not os.path.exists(target):
                Download(download[0], target)


##
## Generate the default configuration file
##

subprocess.check_call([ 'wine', 'Artifacts/Orthanc.exe',
                        '--config=orthanc.json' ],
                      cwd = TARGET)
                                             


##
## Generate the list of components and files
## 

CATEGORIES = {
    'plugins' : 'Official plugins',
    'osimis' : 'Plugins by Osimis',
    'tools' : 'Command-line tools',
    'tools/wsi' : None,
    }

COMPONENTS = []
FILES = []
HAS_CATEGORIES = []

count = 0
for component in CONFIG['Components']:
    if 'Name' in component:
        name = component['Name']
    else:
        name = 'component%02d' % count
        count += 1

    if 'Category' in component:
        category = component['Category']

        if not category in HAS_CATEGORIES and CATEGORIES[category] != None:
            HAS_CATEGORIES.append(category)
            COMPONENTS.append('Name: "%s"; Description: "%s"; Types: full' % (category, CATEGORIES[category]))

        name = '%s\\%s' % (category, name)

    if component['Mandatory']:
        options = 'Types: full compact custom; Flags: fixed'
    else:
        options = 'Types: full'

    COMPONENTS.append('Name: "%s"; Description: "%s"; %s' % (
                        name, component['Description'], options))

    if 'Artifacts' in component:
        for artifact in component['Artifacts']:
            FILES.append('Source: "Artifacts/%s"; DestDir: "{app}/%s"; Components: %s' % (
                        os.path.basename(artifact[0]), artifact[1], name))

    if 'Downloads' in component:
        for download in component['Downloads']:
            FILES.append('Source: "Downloads/%s"; DestDir: "{app}/%s"; Components: %s' % (
                        GetDownloadBasename(download[0]), download[1], name))

    if 'Resources' in component:
        for resource in component['Resources']:
            s = 'Source: "Resources/%s"; DestDir: "{app}/%s"; Components: %s' % (
                resource[0], resource[1], name)

            if resource[1] == 'Configuration':
                s += '; Flags: onlyifdoesntexist uninsneveruninstall'
            
            FILES.append(s)

##
## Compile the Windows service and the configuration generator (always
## as a 32-bit program)
##

subprocess.check_call([ 'cmake', 
                        os.path.abspath(os.path.join(SOURCE, 'Configuration')), 
                        '-DCMAKE_BUILD_TYPE=Release',
                        ],
                      cwd = os.path.join(TARGET, 'Configuration'))

subprocess.check_call([ 'make', '-j4' ],
                      cwd = os.path.join(TARGET, 'Configuration'))


##
## Create the InnoSetup configuration
##

MERCURIAL_REVISION = subprocess.check_output([ 'hg', 'identify', '--num', '-r', '.' ],
                                             cwd = SOURCE)

SETUP_64 = '''
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
'''

with open(os.path.join(SOURCE, 'Installer.innosetup'), 'r') as f:
    installer = f.read()

installer = installer.replace('${ORTHANC_NAME}', CONFIG['Name'])
installer = installer.replace('${ORTHANC_VERSION}', CONFIG['Version'])
installer = installer.replace('${ORTHANC_COMPONENTS}', '\n'.join(COMPONENTS))
installer = installer.replace('${ORTHANC_FILES}', '\n'.join(FILES))
installer = installer.replace('${MERCURIAL_REVISION}', MERCURIAL_REVISION)
installer = installer.replace('${ORTHANC_ARCHITECTURE}', str(ARCHITECTURE))
installer = installer.replace('${ORTHANC_SETUP}', 
                              SETUP_64 if ARCHITECTURE == 64 else '')

with open(os.path.join(TARGET, 'Installer.innosetup'), 'w') as g:
    g.write(installer)


##
## Run InnoSetup
##

subprocess.check_call([ 'wine',
                        'c:/Program Files (x86)/Inno Setup 5/ISCC.exe',
                        'Installer.innosetup' ],
                      cwd = TARGET)

print('\n\nThe installer is inside the following location:\n%s\n\n' % TARGET)
