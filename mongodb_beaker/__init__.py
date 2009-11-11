#
# * Beaker plugin for MongoDB support
#
# Brendan W. McAdams <bwmcadams@gmail.com>
#
"""
==============
mongodb_beaker
==============
MongoDB_. backend for Beaker_.'s caching / session system.

Based upon Beaker_.'s ext:memcache code.

This is implemented in a dont-assume-its-there manner.
It uses the beaker namespace as the mongodb row's _id, with everything
in that namespace ( e.g. a session or cache namespace) stored as a full
document.  Each key/value is part of that compound document, using upserts
for performance.

I will probably add a toggleable option for using subcollections, as in
certain cases such as caching mako templates, this may be desirable / 
preferred performance wise.

Right now, this is primarily optimized for usage with beaker sessions,
although I need to look at tweaking beaker session itself as having it 
store in individual keys rather than everything in a 'session' key may
be desirable for pruning/management/querying. 

I have not tackled expiration yet, so you may want to hold off using this
if you need it.  It will be in the next update, but limits usefulness
primarily to sessions right now. (I'll tack a cleanup script in later 
as well).

Due to the use of upserts, no check-insert is required, but it will overwrite 
previous values which should be expected behavior while caching.
Safe is NOT invoked, so failure will be quiet.
TODO - Safe as overridable config option?

Note that, unless you disable_. it, the mongodb_beaker container will
use pickle (tries loading cpickle first, falls back on pickle) to
serialize/deserialize data to MongoDB_.

.. _Beaker: http://beaker.groovie.org
.. _MongoDB: http://mongodb.org


Beaker should maintain thread safety on connections internally and so I am 
relying upon that rather than setting up threadlocal, etc.  If this assumption
is wrong or you run into issues, please let me know.

Configuration
=============

To set this up in your own project so that beaker can find it, it must
define a setuptools entry point in your setup.py file.  If you install 
from the egg distribution, mongodb_beaker's setup.py SHOULD create a 
beaker.backend entry point.  If you need to tweak it/see how it's done
or it just doesn't work and you need to define your own, 
mine looks like this::

    >>> entry_points=\"\"\"
    ... [beaker.backends]
    ... mongodb = mongodb_beaker:MongoDBNamespaceManager
    ... \"\"\",


With this defined, beaker should automatically find the entry point at startup
(Beaker 1.4 and higher support custom entry points) and load it as an optional
backend called 'mongodb'. There are several ways to configure Beaker, I only 
cover ini file (such as with Pylons) here.  There are more configuration 
options and details in the Beaker configuration docs [1]_.

.. [1] Beaker's configuration documentation -
        http://beaker.groovie.org/configuration.htm
    
I have a few cache regions in one of my applications, some of which are memcache and some are on mongodb.  The region config looks like this::

    >>> # new style cache settings
    ... beaker.cache.regions = comic_archives, navigation
    ... beaker.cache.comic_archives.type = libmemcached
    ... beaker.cache.comic_archives.url = 127.0.0.1:11211
    ... beaker.cache.comic_archives.expire = 604800
    ... beaker.cache.navigation.type = mongodb
    ... beaker.cache.navigation.url = \
            mongodb://localhost:27017/beaker#navigation
    ... beaker.cache.navigation.expire = 86400
 
The Beaker docs[1] contain detailed information on configuring regions.  The
item we're interested in here is the **beaker.cache.navigation** keys.  Each
beaker cache definition needs a *type* field, which defines which backend to
use.  Specifying mongodb will (if the module is properly installed) tell
Beaker to cache via mongodb.  Note that if Beaker cannot load the extension,
it will tell you that mongodb is an invalid backend.

Expiration is standard beaker syntax, although not supported at the moment in
this backend.  

Finally, you need to define a URL to connect to MongoDB.  For succinctness,
I've chosen to define a RFC 1738 URL.  Your url must start with mongodb://.
The syntax is hostname:port/database#collection. You must define a collection
for MongoDB to store data in, in addition to a database.  

If you want to use MongoDB's optional authentication support, that is also supported.  Simply define your URL as such::

    >>> beaker.cache.navigation.url = \
            mongodb://bwmcadams@passW0Rd?@localhost:27017/beaker#navigation

The mongodb_beaker backend will attempt to authenticate with the username and
password.  You must configure MongoDB's optional authentication support[2] for
this to work (By default MongoDB doesn't use authentication).

.. [2] MongoDB Authentication Documentation

Using Beaker Sessions and disabling pickling
=============================================

.. _disable:

If you want to save some CPU cycles and can guarantee that what you're
passing in is either "mongo-safe" and doesn't need pickling, or you know
it's already pickled (such as while using beaker sessions), you can set an
extra beaker config flag of skip_pickle=True.  ``.. admonition:: To make that
perfectly clear, Beaker sessions are ALREADY PASSED IN pickled, so you want to 
configure it to skip_pickle.`` It shouldn't hurt anything to double-pickle,
but you will certainly waste precious CPU cycles.  And wasting CPU cycles is 
kind of counterproductive in a caching system.  

My pylons application configuration for mongodb_beaker has the
following session_configuration::

    >>> beaker.session.type = mongodb
    ... beaker.session.url = mongodb://localhost:27017/beaker#sessions
    ... beaker.session.skip_pickle = True

Note the use of a 
Depending on your individual needs, you may also wish to create a 
capped collection for your caching (e.g. memcache-like only most recently used storage)

See the MongoDB CappedCollection_. docs for details.

.. _CappedCollection: http://www.mongodb.org/display/DOCS/Capped+Collections

"""
import logging
from beaker.container import NamespaceManager, Container
from beaker.exceptions import InvalidCacheBackendError, MissingCacheParameter
from beaker.synchronization import file_synchronizer
from beaker.util import verify_directory, SyncDict

from StringIO import StringIO
try:
    import cPickle as pickle
except ImportError:
    import pickle

try:
    import pymongo.connection
except ImportError:
    raise InvalidCacheBackendError("Unable to load the pymongo driver.")

log = logging.getLogger(__name__)


def parse_mongo_url(mongo_url):
    """Parses a MongoDB connection string.  String format::

        >>> beaker.session.mongo_url = \
                mongodb://user:passwd@localhost:27017/beaker#sessions

        Standard URL similar to SQLAlchemy. Use #fragment for collection name.
        Uses modified code from Python's mongo_urlparse
    """
    if not mongo_url.startswith("mongodb://"):
        raise MissingCacheParameter("Invalid MongoDB connection string.")

    scheme = mongo_url.lower()
    mongo_url = mongo_url.split("mongodb://", 1)[1]
    if '#' in mongo_url:
        mongo_url, collection = mongo_url.split('#', 1)
    if '/' in mongo_url:
        mongo_url, database = mongo_url.split('/', 1)

    # Parse URL / password if they exist
    head, sep, tail = mongo_url.partition('@')
    username = password = None
    if sep:
        if head.find(':') > -1:
            username, password = head.split(':', 1)
        mongo_url = tail

    port = 27017
    if mongo_url.find(':') > -1:
        mongo_url, port = mongo_url.split(':')
        try:
            port = int(port)
        except:
            port = 27017
            pass


    return {'username': username,
            'password': password,
            'host': mongo_url,
            'port': port,
            'database': database,
            'collection': collection}


class MongoDBNamespaceManager(NamespaceManager):
    clients = SyncDict()
    _pickle = True
    _sparse = False

    def __init__(self, namespace, url=None, data_dir=None,
                 lock_dir=None, skip_pickle=False, 
                 sparse_collection=False, **params):
        NamespaceManager.__init__(self, namespace)

        if not url:
            raise MissingCacheParameter("MongoDB url is required")

        if skip_pickle:
            log.info("Disabling pickling for namespace: %s" % self.namespace)
            _pickle = False

        if sparse_collection:
            log.info("Separating data to one row per key (sparse collection) for ns %s ." % self.namespace)
            self._sparse = True

        conn_params = parse_mongo_url(url)
        if conn_params['database'] and conn_params['host'] and \
          conn_params['collection']:
            data_key = "mongodb:%s#%s" % (conn_params['database'],
                                          conn_params['collection'])
        else:
            raise MissingCacheParameter("Invalid Cache URL.  Cannot parse"
                                        " host, database and/or "
                                        " collection name.")
        # Key will be db + collection
        if lock_dir:
            self.lock_dir = lock_dir
        elif data_dir:
            self.lock_dir = data_dir + "/container_mongodb_lock"
        if self.lock_dir:
            verify_directory(self.lock_dir)

        def _create_mongo_conn():
            conn = pymongo.connection.Connection(conn_params['host'],
                                                 conn_params['port'])

            db = conn[conn_params['database']]

            if conn_params['username'] and conn_params['password']:
                log.info("Attempting to authenticate %s/%s " %
                         conn_params['username'],
                         conn_params['password'])
                if not db.authenticate(conn_params['username'],
                                       conn_params['password']):
                    raise InvalidCacheBackendError('Cannot authenticate to '
                                                   ' MongoDB.')
            return db[conn_params['collection']]

        self.mongo = MongoDBNamespaceManager.clients.get(data_key,
                    _create_mongo_conn)

    def get_creation_lock(self, key):
        """@TODO - stop hitting filesystem for this...
        """
        return file_synchronizer(
            identifier = "mongodb_container/funclock/%s" % self.namespace,
            lock_dir = self.lock_dir)

    def do_remove(self):
        "Clears the entire filesystem (drops the collection)"
        log.debug("[MongoDB] Remove namespace: %s" % self.namespace)
        if self._sparse:
            import re
            self.mongo.remove({'_id': re.compile('^%s#' % self.namespace)})
        else:
            self.mongo.remove({'_id': self.namespace})

        #raise NotImplementedError()

    def __getitem__(self, key):
        log.debug("[MongoDB %s] Get Key: %s" % (self.mongo,
                                                key))

        if self._sparse:
            result = self.mongo.find(spec={'_id': '%s#%s' % (self.namespace, key)},
                                     fields=['data'], limit=-1)
        else:
            result = self.mongo.find(spec={'_id': self.namespace},
                                     fields=[key], limit=-1)
        if result > 0: 
            """Running into instances in which mongo is returning
            -1, which causes an error as __len__ should return 0 
            or positive integers, hence the check of size explicit"""
            for item in result:
                value = item.get(key, None)
                if self._pickle:
                    try:
                        value = pickle.loads(value.encode('utf-8'))
                    except:
                        log.exception("Failed to unpickle value.")
                    
                return value


    def __contains__(self, key):
        if self._sparse:
            ns = '%s#%s' % (self.namespace, key) 
        else: 
            ns = self.namespace

        log.debug("[MongoDB %s] Contains Key? %s" % (ns,
                                                     key))
        result = self.mongo.find_one({'_id': ns},
                                    fields=[key])
        log.debug("Result: %s" % result)
        if result: 
            for item in result:
                return item.get(key, None) is not None
        else:
            return False

    def has_key(self, key):
        return key in self

    def __setitem__(self, key, value):
        log.debug("[MongoDB %s] Set Key: %s ... " % (self.mongo,
                                                     key))
        if self._pickle:
            try:
                value = pickle.dumps(value)
            except:
                log.exception("Failed to pickle value.")

        if self._sparse:
            self.mongo.insert({
                '_id': "%s#%s" % (self.namespace, key),
                'data': value
            })
        else:                 
            self.mongo.update({'_id': self.namespace}, 
                {'$set': {key: value}},
                upsert=True
            )

    def __delitem__(self, key):
        """Delete JUST the key, by setting it to None."""
        if self._sparse:
            self.mongo.remove({
                '_id': "%s#%s" % (self.namespace, key)
            })
        else:
            self.mongo.update({'_id': self.namespace}, 
                {'$set': {key: None}},
                upsert=False
            )

    def keys(self):
        if self._sparse:
            keys = [row['_id'].replace(self.namespace + '#', '') for row in self.mongo.find()]
        else:
            keys = self.mongo.find_one({'_id': self.namespace})
            keys.remove('_id')
        return keys


class MongoDBContainer(Container):
    namespace_class = MongoDBNamespaceManager
