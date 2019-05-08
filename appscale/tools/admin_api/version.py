""" Represents an Admin API Version resource. """

from __future__ import absolute_import

import tarfile
import zipfile
from xml.etree import ElementTree

import yaml

from appscale.tools.admin_api.client import DEFAULT_SERVICE
from appscale.tools.admin_api.handler import Handler
from appscale.tools.custom_exceptions import AppEngineConfigException
from appscale.tools.utils import shortest_directory_path, shortest_path_from_list

# The namespace that appengine-web.xml uses.
XML_NAMESPACE = '{http://appengine.google.com/ns/1.0}'


class Version(object):
  """ Represents an Admin API Version resource. """
  def __init__(self, runtime, config_type):
    """ Creates a new Version.

    Args:
      runtime: A string specifying the runtime.
      config_type: A string specifying what type of config file was used.
    """
    # TODO: Pass runtime unmodified when backend recognizes 'java7'.
    if runtime == 'java7':
      runtime = 'java'

    self.runtime = runtime
    self.config_type = config_type

    self.project_id = None
    self.service_id = None

    # The version ID.
    # TODO: Allow user to define this property.
    self.id = None

    self.env_variables = {}
    self.inbound_services = []
    self.threadsafe = None
    self.handlers = None
    self.manual_scaling = None
    self.automatic_scaling = None
    self.serving_status = None

  @staticmethod
  def from_yaml(app_yaml):
    """ Constructs a Version from a parsed app.yaml.

    Args:
      app_yaml: A dictionary generated by a parsed app.yaml.
    Returns:
      A Version object.
    Raises:
      AppengineConfigException if app_yaml is invalid.
    """
    try:
      runtime = app_yaml['runtime']
    except KeyError:
      raise AppEngineConfigException('Missing app.yaml element: runtime')

    try:
      handlers = app_yaml['handlers']
    except KeyError:
      raise AppEngineConfigException('Missing app.yaml element: handlers')

    version = Version(runtime, 'app.yaml')
    version.project_id = app_yaml.get('application')
    version.handlers = [Handler.from_yaml(handler) for handler in handlers]

    if 'service' in app_yaml and 'module' in app_yaml:
      raise AppEngineConfigException(
        'Invalid app.yaml: If "service" is defined, "module" cannot be '
        'defined.')

    version.service_id = (app_yaml.get('service') or app_yaml.get('module')
                          or DEFAULT_SERVICE)

    version.env_variables = app_yaml.get('env_variables', {})
    version.inbound_services = app_yaml.get('inbound_services', [])

    automatic_scaling = app_yaml.get('automatic_scaling', None)
    manual_scaling = app_yaml.get('manual_scaling', None)
    if automatic_scaling and manual_scaling:
      raise AppEngineConfigException(
        'Invalid app.yaml: If "automatic_scaling" is defined, "manual_scaling" '
        'cannot be defined.')
    elif manual_scaling:
      try:
        version.manual_scaling = {'instances': int(manual_scaling['instances'])}
      except StandardError:
        raise AppEngineConfigException('Invalid app.yaml: manual_scaling invalid.')
    elif automatic_scaling:
        try:
            version.automatic_scaling = {'standardSchedulerSettings': {
                'minInstances': int(automatic_scaling['min_instances']),
                'maxInstances': int(automatic_scaling['max_instances'])
            }}
        except StandardError:
            raise AppEngineConfigException('Invalid app.yaml: automatic_scaling invalid.')

        # Adds optional elements for automatic scaling.
        try:
            min_idle = automatic_scaling.get('min_idle_instances')
            if min_idle is not None:
                version.automatic_scaling['minIdleInstances'] = int(min_idle)
            max_idle = automatic_scaling.get('max_idle_instances')
            if max_idle is not None:
                version.automatic_scaling['maxIdleInstances'] = int(max_idle)
            max_concurrent = automatic_scaling.get('max_concurrent_requests')
            if max_concurrent is not None:
                version.automatic_scaling['maxConcurrentRequests'] =
                                          int(max_concurrent)
        except ValueError:
            raise AppEngineConfigException('Invalid app.yaml: value for '
                    'automatic scaling option is not integer.')

    if version.runtime in ('python27', 'java'):
      try:
        version.threadsafe = app_yaml['threadsafe']
      except KeyError:
        raise AppEngineConfigException(
          'Invalid app.yaml: {} applications require the "threadsafe" '
          'element'.format(version.runtime))

      if not isinstance(version.threadsafe, bool):
        raise AppEngineConfigException(
          'Invalid app.yaml: "threadsafe" must be a boolean')

    return version

  @staticmethod
  def from_xml(root):
    """ Constructs a Version from a parsed appengine-web.xml.

    Args:
      root: An XML Element object representing the document root.
    Returns:
      A Version object.
    """
    qname = lambda name: ''.join([XML_NAMESPACE, name])
    runtime_element = root.find(qname('runtime'))
    runtime = 'java7'
    if runtime_element is not None:
      runtime = runtime_element.text

    version = Version(runtime, 'appengine-web.xml')

    application_element = root.find(qname('application'))
    if application_element is not None:
      version.project_id = application_element.text

    service_element = root.find(qname('service'))
    module_element = root.find(qname('module'))
    if service_element is not None and module_element is not None:
      raise AppEngineConfigException(
        'Invalid appengine-web.xml: If "service" is defined, "module" cannot '
        'be defined.')

    if module_element is not None:
      version.service_id = module_element.text

    if service_element is not None:
      version.service_id = service_element.text

    if not version.service_id:
      version.service_id = DEFAULT_SERVICE

    env_vars_element = root.find(qname('env-variables'))
    if env_vars_element is not None:
      version.env_variables = {var.attrib['name']: var.attrib['value']
                               for var in env_vars_element}

    inbound_services = root.find(qname('inbound-services'))
    if inbound_services is not None:
      version.inbound_services = [service.text for service in inbound_services]

    automatic_scaling = root.find(qname('automatic-scaling'))
    manual_scaling = root.find(qname('manual-scaling'))
    if automatic_scaling is not None and manual_scaling is not None:
      raise AppEngineConfigException(
        'Invalid appengine-web.xml: If "automatic-scaling" is defined, '
        '"manual-scaling" cannot be defined.')
    elif manual_scaling is not None:
        try:
            version.manual_scaling = {
                'instances': int(manual_scaling.findtext(qname('instances')))}
        except StandardError:
            raise AppEngineConfigException('Invalid app.yaml: manual_scaling invalid.')
    elif automatic_scaling is not None:
        try:
            version.automatic_scaling = {'standardSchedulerSettings': {
                'minInstances': int(automatic_scaling.findtext(qname('min-instances'))),
                'maxInstances': int(automatic_scaling.findtext(qname('max-instances')))}}
        except StandardError:
            raise AppEngineConfigException('Invalid app.yaml: automatic_scaling invalid.')

    # Adds optional elements for automatic scaling.
    try:
        min_idle = root.find(qname('min-idle-instances'))
        if min_idle is not None:
            version.automatic_scaling['minIdleInstances'] = int(min_idle)
        max_idle = root.find(qname('max-idle-instances'))
        if max_idle is not None:
            version.automatic_scaling['maxIdleInstances'] = int(max_idle)
        max_concurrent = root.find(qname('max-concurrent-requests'))
        if max_idle is not None:
            version.automatic_scaling['maxConcurrentRequests'] =
                                         int(max_concurrent)
    except ValueError:
        raise AppEngineConfigException('Invalid appengine-web.xml: value for '
                'automatic scaling option is not integer.')

    threadsafe_element = root.find(qname('threadsafe'))
    if threadsafe_element is None:
      raise AppEngineConfigException(
        'Invalid appengine-web.xml: missing "threadsafe" element')

    if threadsafe_element.text.lower() not in ('true', 'false'):
      raise AppEngineConfigException(
        'Invalid appengine-web.xml: Invalid "threadsafe" value. '
        'It must be either "true" or "false".')

    version.threadsafe = threadsafe_element.text.lower() == 'true'

    return version

  @staticmethod
  def from_yaml_file(yaml_location):
    """ Constructs a Version from an app.yaml file.

    Args:
      yaml_location: A string specifying the location to an app.yaml.
    Returns:
      A Version object.
    Raises:
      AppengineConfigException if the app.yaml is invalid or missing.
    """
    try:
      with open(yaml_location) as yaml_file:
        try:
          app_yaml = yaml.safe_load(yaml_file)
        except yaml.YAMLError as error:
          raise AppEngineConfigException('Invalid app.yaml: {}'.format(error))

        return Version.from_yaml(app_yaml)
    except IOError:
      raise AppEngineConfigException('Unable to read {}'.format(yaml_location))

  @staticmethod
  def from_xml_file(xml_location):
    """ Constructs a Version from an appengine-web.xml file.

    Args:
      xml_location: A string specifying the location to an appengine-web.xml.
    Returns:
      A Version object.
    Raises:
      AppengineConfigException if the appengine-web.xml is invalid or missing.
    """
    try:
      tree = ElementTree.parse(xml_location)
    except (IOError, ElementTree.ParseError) as error:
      raise AppEngineConfigException('Invalid appengine-web.xml: {}'.format(error))

    return Version.from_xml(tree.getroot())

  @staticmethod
  def from_directory(source_location):
    """ Constructs a Version from a directory.

    Args:
      source_location: A string specifying a path to the source directory.
    Returns:
      A Version object.
    Raises:
      AppengineConfigException if the app's config file is invalid or missing.
    """
    config_location = shortest_directory_path('app.yaml', source_location)
    if config_location is not None:
      return Version.from_yaml_file(config_location)

    config_location = shortest_directory_path('appengine-web.xml',
                                              source_location)
    if config_location is not None:
      return Version.from_xml_file(config_location)

    raise AppEngineConfigException(
      'Unable to find app.yaml or appengine-web.xml')

  @staticmethod
  def from_contents(contents, file_name):
    """ Constructs a Version from the contents of a config file.

    Args:
      contents: A string containing the entire configuration contents.
      file_name: A string specifying the type of config file
        (app.yaml or appengine-web.xml).
    Returns:
      A Version object.
    Raise:
      AppengineConfigException if the configuration contents are invalid.
    """
    if file_name == 'app.yaml':
      try:
        app_yaml = yaml.safe_load(contents)
      except yaml.YAMLError as error:
        raise AppEngineConfigException('Invalid app.yaml: {}'.format(error))

      return Version.from_yaml(app_yaml)
    else:
      try:
        appengine_web_xml = ElementTree.fromstring(contents)
      except ElementTree.ParseError as error:
        raise AppEngineConfigException(
          'Invalid appengine-web.xml: {}'.format(error))

      return Version.from_xml(appengine_web_xml)

  @staticmethod
  def from_tar_gz(tar_location):
    """ Constructs a Version from a gzipped tarball.

    Args:
      tar_location: A string specifying a location to a gzipped tarball.
    Returns:
      A Version object.
    Raises:
      AppengineConfigException if the config is invalid or cannot be extracted.
    """
    with tarfile.open(tar_location, 'r:gz') as tar:
      file_name = 'app.yaml'
      name_list = [member.name for member in tar.getmembers()]
      config_location = shortest_path_from_list(file_name, name_list)
      if config_location is None:
        file_name = 'appengine-web.xml'
        config_location = shortest_path_from_list(file_name, name_list)

      if config_location is None:
        raise AppEngineConfigException(
          'Unable to find app.yaml or appengine-web.xml')

      config_file = tar.extractfile(config_location)
      try:
        contents = config_file.read()
      finally:
        config_file.close()

      return Version.from_contents(contents, file_name)

  @staticmethod
  def from_zip(zip_location):
    """ Constructs a Version from a zip file.

    Args:
      zip_location: A string specifying a location to a zip file.
    Returns:
      A Version object.
    Raises:
      AppengineConfigException if the config is invalid or cannot be extracted.
    """
    with zipfile.ZipFile(zip_location) as zip_file:
      file_name = 'app.yaml'
      name_list = zip_file.namelist()
      config_location = shortest_path_from_list(file_name, name_list)
      if config_location is None:
        file_name = 'appengine-web.xml'
        config_location = shortest_path_from_list(file_name, name_list)

      if config_location is None:
        raise AppEngineConfigException(
          'Unable to find app.yaml or appengine-web.xml')

      with zip_file.open(config_location) as config_file:
        contents = config_file.read()

      return Version.from_contents(contents, file_name)
