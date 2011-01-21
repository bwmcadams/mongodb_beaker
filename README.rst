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

    >>> entry_points="""
    ... [beaker.backends]
    ... mongodb = mongodb_beaker:MongoDBNamespaceManager
    ... """,


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
    ... beaker.cache.navigation.url = mongodb://localhost:27017/beaker.navigation
    ... beaker.cache.navigation.expire = 86400
 
The Beaker docs[1] contain detailed information on configuring regions.  The
item we're interested in here is the **beaker.cache.navigation** keys.  Each
beaker cache definition needs a *type* field, which defines which backend to
use.  Specifying mongodb will (if the module is properly installed) tell
Beaker to cache via mongodb.  Note that if Beaker cannot load the extension,
it will tell you that mongodb is an invalid backend.

Expiration is standard beaker syntax, although not supported at the moment in
this backend.

Finally, you need to define a URL to connect to MongoDB.  This follows the standardized
MongoDB URI Format[3]_. Currently the only options supported is 'slaveOK'.
For backwards compatibility with old versions of mongodb_beaker, separating
database and collection with a '#' instead of '.' is supported, but deprecated.
The syntax is mongodb://<hostname>[:port]/<database>.<collection>

You must define a collection for MongoDB to store data in, in addition to a database.

If you want to use MongoDB's optional authentication support, that is also supported.  Simply define your URL as such::

    >>> beaker.cache.navigation.url = mongodb://bwmcadams@passW0Rd?@localhost:27017/beaker.navigation

The mongodb_beaker backend will attempt to authenticate with the username and
password.  You must configure MongoDB's optional authentication support[2]_ for
this to work (By default MongoDB doesn't use authentication).

.. [2] MongoDB Authentication Documentation: http://www.mongodb.org/display/DOCS/Security+and+Authentication
.. [3] MongoDB URI Format: http://www.mongodb.org/display/DOCS/Connections


Reading from Secondaries (SlaveOK)
==================================

If you'd like to enable reading from secondaries (SlaveOK), you can add that to your URL::

    >>> beaker.cache.navigation.url = mongodb://bwmcadams@passW0Rd?@localhost:27017/beaker.navigation?slaveok=true


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
    ... beaker.session.url = mongodb://localhost:27017/beaker.sessions
    ... beaker.session.skip_pickle = True

Depending on your individual needs, you may also wish to create a
capped collection for your caching (e.g. memcache-like only most recently used storage)

See the MongoDB CappedCollection_. docs for details.

.. _CappedCollection: http://www.mongodb.org/display/DOCS/Capped+Collections

Sparse Collection Support
=========================

The default behavior of mongodb_beaker is to create a single MongoDB Document for each namespace, and store each 
cache key/value on that document.  In this case, the "_id" of the document will be the namespace, and each new cache entry
will be attached to that document.

This approach works well in many cases and makes it very easy for Mongo to efficiently manage your cache.  However, in other cases
you may wish to change behavior.  This may be for efficiency reasons, or because you're worried about documents getting too large.

In this case, you can enable a "sparse collection" mode, where mongodb_beaker will create a document for EACH key in the namespace.
When sparse collections are enabled, the "_id" of a document is a compound document containing the namespace and the key::

   { "_id" : { "namespace" : "testcache", "key" : "value" } }

The cache data for that key will be stored in a document field 'data'.  You can enable sparse collections in your config with the
'sparse_collections' variable::

    >>> beaker.session.type = mongodb
    ... beaker.session.url = mongodb://localhost:27017/beaker.sessions
    ... beaker.session.sparse_collections = True

Note for Users of Previous Releases
====================================

For bug fix and feature reasons, MongoDB Beaker 0.5+ are not compatible with caches created by previous releases.
Because this is cache data, it shouldn't be a big deal.  We recommend dropping or flushing your entire cache collection(s)
before upgrading to 0.5+ and be aware that it will generate new caches.


