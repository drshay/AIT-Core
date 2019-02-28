import gevent
import gevent.monkey; gevent.monkey.patch_all()
from importlib import import_module
import sys

# import ait
import ait.core.server
from stream import PortInputStream, ZMQInputStream, PortOutputStream
from broker import AITBroker
from ait.core import log, cfg


class AITServer(object):
    """
    This server reads and parses config.yaml to create all streams, plugins and handlers
    specified. It starts all greenlets that run these components and calls on the broker
    to manage the ZeroMQ connections.
    """
    inbound_streams = [ ]
    outbound_streams = [ ]
    servers = [ ]
    plugins = [ ]

    def __init__(self):
        self.broker = AITBroker()

        self._load_streams()
        self._load_plugins()

        self.broker.inbound_streams = self.inbound_streams
        self.broker.outbound_streams = self.outbound_streams
        self.broker.servers = self.servers
        self.broker.plugins = self.plugins

        # defining greenlets that need to be joined over
        self.greenlets = ([self.broker] +
                           self.broker.plugins +
                           self.broker.inbound_streams +
                           self.broker.outbound_streams)

    def wait(self):
        """
        Starts all greenlets for concurrent processing.
        Joins over all greenlets that are not servers.
        """
        for greenlet in (self.greenlets + self.servers):
            log.info("Starting {} greenlet...".format(greenlet))
            greenlet.start()

        gevent.joinall(self.greenlets)

    def _load_streams(self):
        """
        Reads, parses and creates streams specified in config.yaml.
        """
        common_err_msg = 'No valid {} telemetry stream configurations found. '
        specific_err_msg = {'inbound': 'No telemetry will be received (or displayed).',
                            'outbound': 'No telemetry will be published.'}
        err_msgs = {}

        for stream_type in ['inbound', 'outbound']:
            err_msgs[stream_type] = common_err_msg.format(stream_type) + specific_err_msg[stream_type]
            streams = ait.config.get('server.{}-streams'.format(stream_type))

            if streams is None:
                log.warn(err_msgs[stream_type])
            else:
                for index, s in enumerate(streams):
                    try:
                        strm = self._create_stream(s['stream'], stream_type)
                        if stream_type == 'inbound' and type(strm) == PortInputStream:
                            self.servers.append(strm)
                        elif stream_type == 'inbound':
                            self.inbound_streams.append(strm)
                        elif stream_type == 'outbound':
                            self.outbound_streams.append(strm)
                        log.info('Added {} stream {}'.format(stream_type, strm))
                    except Exception:
                        exc_type, value, tb = sys.exc_info()
                        log.error('{} creating {} stream {}: {}'.format(exc_type,
                                                                        stream_type,
                                                                        index,
                                                                        value))
        if not self.inbound_streams and not self.servers:
            log.warn(err_msgs['inbound'])

        if not self.outbound_streams:
            log.warn(err_msgs['outbound'])

    def _create_stream(self, config, stream_type):
        """
        Creates a stream from its config.

        Params:
            config:       stream configuration as read by ait.config
            stream_type:  either 'inbound' or 'outbound'
        Returns:
            stream:       a Stream
        Raises:
            ValueError:   if any of the required config values are missing
        """
        if stream_type not in ['inbound', 'outbound']:
            raise ValueError('Stream type must be \'inbound\' or \'outbound\'.')

        if config is None:
            raise ValueError('No stream config to create stream from.')

        name = config.get('name', None)
        if name is None:
            raise(cfg.AitConfigMissing(stream_type + ' stream name'))
        if name in [x.name for x in (self.outbound_streams +
                                     self.inbound_streams +
                                     self.servers +
                                     self.plugins)]:
            raise ValueError('Stream name already exists. Please rename.')

        stream_input = config.get('input', None)
        if stream_input is None and stream_type is 'inbound':
            raise(cfg.AitConfigMissing(stream_type + ' stream input'))

        stream_handlers = [ ]
        if 'handlers' in config:
            if config['handlers'] is not None:
                for handler in config['handlers']:
                    hndlr = self._create_handler(handler)
                    stream_handlers.append(hndlr)
                    log.info('Created handler {} for stream {}'.format(type(hndlr).__name__,
                                                                       name))
        else:
            log.warn('No handlers specified for {} stream {}'.format(stream_type,
                                                                     name))

        stream_output = config.get('output', None)
        if type(stream_output) is int and stream_type is 'outbound':
            return PortOutputStream(name,
                                    stream_input,
                                    stream_output,
                                    stream_handlers,
                                    zmq_args={'zmq_context': self.broker.context,
                                              'zmq_proxy_xsub_url': self.broker.XSUB_URL,
                                              'zmq_proxy_xpub_url': self.broker.XPUB_URL})
        elif type(stream_input) is int:
            return PortInputStream(name,
                                   stream_input,
                                   stream_handlers,
                                   zmq_args={'zmq_context': self.broker.context,
                                             'zmq_proxy_xsub_url': self.broker.XSUB_URL,
                                             'zmq_proxy_xpub_url': self.broker.XPUB_URL})
        else:
            return ZMQInputStream(name,
                                  stream_input,
                                  stream_handlers,
                                  zmq_args={'zmq_context': self.broker.context,
                                            'zmq_proxy_xsub_url': self.broker.XSUB_URL,
                                            'zmq_proxy_xpub_url': self.broker.XPUB_URL})

    def _create_handler(self, config):
        """
        Creates a handler from its config.

        Params:
            config:      handler config
        Returns:
            handler instance
        """
        if config is None:
            raise ValueError('No handler config to create handler from.')

        if 'name' not in config:
            raise ValueError('Handler name is required.')

        handler_name = config['name']
        # try to create handler
        module_name = handler_name.rsplit('.', 1)[0]
        class_name = handler_name.rsplit('.', 1)[-1]
        module = import_module(module_name)
        handler_class = getattr(module, class_name)
        instance = handler_class(**config)

        return instance

    def _load_plugins(self):
        """
        Reads, parses and creates plugins specified in config.yaml.
        """
        plugins = ait.config.get('server.plugins')

        if plugins is None:
            log.warn('No plugins specified in config.')
        else:
            for index, p in enumerate(plugins):
                try:
                    plugin = self._create_plugin(p['plugin'])
                    self.plugins.append(plugin)
                    log.info('Added plugin {}'.format(plugin))

                except Exception:
                    exc_type, value, tb = sys.exc_info()
                    log.error('{} creating plugin {}: {}'.format(exc_type,
                                                                 index,
                                                                 value))
            if not self.plugins:
                log.warn('No valid plugin configurations found. No plugins will be added.')

    def _create_plugin(self, config):
        """
        Creates a plugin from its config.

        Params:
            config:       plugin configuration as read by ait.config
        Returns:
            plugin:       a Plugin
        Raises:
            ValueError:   if any of the required config values are missing
        """
        if config is None:
            raise ValueError('No plugin config to create plugin from.')

        name = config.get('name', None)
        if name is None:
            raise(cfg.AitConfigMissing('plugin name'))

        # TODO I don't think we actually care about this being unique? Left over from
        # previous conversations about stuff?
        module_name = name.rsplit('.', 1)[0]
        class_name = name.rsplit('.', 1)[-1]
        if class_name in [x.name for x in (self.outbound_streams +
                                           self.inbound_streams +
                                           self.servers +
                                           self.plugins)]:
            raise ValueError(
                'Plugin "{}" already loaded. Only one plugin of a given name is allowed'.
                format(class_name)
            )

        plugin_inputs = config.get('inputs', None)
        if plugin_inputs is None:
            log.warn('No plugin inputs specified for {}'.format(name))
            plugin_inputs = [ ]

        subscribers = config.get('outputs', None)
        if subscribers is None:
            log.warn('No plugin outputs specified for {}'.format(name))
            subscribers = [ ]

        # try to create plugin
        module = import_module(module_name)
        plugin_class = getattr(module, class_name)
        instance = plugin_class(plugin_inputs,
                                subscribers,
                                zmq_args={'zmq_context': self.broker.context,
                                          'zmq_proxy_xsub_url': self.broker.XSUB_URL,
                                          'zmq_proxy_xpub_url': self.broker.XPUB_URL})

        return instance