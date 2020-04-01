# Galicaster One Button Studio Plugin

This Galicaster (https://github.com/teltek/Galicaster) plugin links the complete One Button Studio process flow:

1. Retrieves bookings made from Outlook (https://github.com/cilt-uct/obs-webservice) and adds a "My Videos" tool linked to Vula [Sakai (https://github.com/sakaiproject/sakai)].
2. Communicates with Opencast (https://github.com/opencast/opencast) to:
  * Link to personal series or
  * Create personal series if it doesn't exist.
  
  _NOTE:_ if you just want this functonality it is available in this plugin: Galicaster Select User (https://github.com/cilt-uct/galicaster-select-user).
  
3. Integrates with the Powermate Button to trigger recordings.
4. Control the Mascot light and Notification lights (Red for recording / Green for ready).
5. After upload/ingest the "My Videos" will be created in a workflow if it doesn't already exists.

## Installation

1. Copy `obs.py` to `/[path to install]/Galicaster/galicaster/plugins/obs.py`
2. Copy over the content of `resources/ui` to `/[path to install]/Galicaster/resources/ui`
3. If not already part of the codebase also copy:
  * `galicaster/classui/recorderui.py` to `/[path to install]/Galicaster/galicaster/classui/recorderui.py`
  * `galicaster/opencast/client.py` to `/[path to install]/Galicaster/galicaster/opencast/client.py`

_NOTE:_
  * `galicaster/classui/recorderui.py` contains changes to display the name of the selected user.
  * `galicaster/opencast/client.py` contains new methods that are used to communicate with Opencast External API.
  * `resources/ui/series_metadata_template.json` contains the template for creating the metadata for the new series.
  * `resources/ui/acl_template.json` contains the template for creating ACL's for the new series.
  * `resources/ui/set_user.glade` contains the UI elemnts for popup that shows the user selection input.

## Configuration
```
vi /etc/galicaster/conf.ini

[plugins]
obs = True

[obs]
# The regular expression that defines a valid student, staff, or temporary staff number
rexexp = "[0-9]{8}|[a-zA-Z]{6}[0-9]{3}|[T|t][0-9]{7}"

# Additional filter parameters that might be usefull in finding the correct type of series
# e.g ,subject:Personal
filter = "%2Csubject%3APersonal"
```
