'''
Bottle-PgSQL is based on Bottle-MySQL and Bottle-sqlite.
Bottle-PgSQL is a plugin that integrates PostgreSQL with your Bottle
application. It automatically connects to a database at the beginning of a
request, passes the database handle to the route callback and closes the
connection afterwards.

To automatically detect routes that need a database connection, the plugin
searches for route callbacks that require a `db` keyword argument
(configurable) and skips routes that do not. This removes any overhead for
routes that don't need a database connection.

Results are returned as dictionaries.

Usage Example::

    import bottle
    import bottle_pgsql

    app = bottle.Bottle()
    plugin = bottle_pgsql.Plugin('dbname=db user=user password=pass')
    app.install(plugin)

    @app.route('/show/:item')
    def show(item, db):
        db.execute('SELECT * from items where name="%s"', (item,))
        row = db.fetchone()
        if row:
            return template('showitem', page=row)
        return HTTPError(404, "Page not found")
'''

__author__ = "Arif Kurniawan"
__version__ = '0.2-by frodrigo'
__license__ = 'MIT'

### CUT HERE (see setup.py)

import psycopg2
import psycopg2.extras
import inspect
from bottle import HTTPError, PluginError
from bottle import HTTPResponse


class PgSQLPlugin(object):
    ''' This plugin passes a pgsql database handle to route callbacks
    that accept a `db` keyword argument. If a callback does not expect
    such a parameter, no connection is made. You can override the database
    settings on a per-route basis. '''

    name = 'pgsql'
    api  = 2

    def __init__(self, dsn=None, autocommit=False, autorollback=True,
                 keyword='db'):
        self.dsn = dsn
        self.autocommit = autocommit
        self.autorollback = autorollback
        self.keyword = keyword
        self.con = None

    def init_connection(self):
        #con = psycopg2.connect(dsn)
        psycopg2.extensions.register_adapter(dict, psycopg2.extras.Json)
        self.con = psycopg2.extras.DictConnection(self.dsn)
        psycopg2.extras.register_default_jsonb(self.con)
        # Using DictCursor lets us return result as a dictionary instead of the default list

    def setup(self, app):
        ''' Make sure that other installed plugins don't affect the same
            keyword argument.'''
        for other in app.plugins:
            if not isinstance(other, PgSQLPlugin): continue
            if other.keyword == self.keyword:
                raise PluginError("Found another pgsql plugin with "\
                "conflicting settings (non-unique keyword).")

    def apply(self, callback, route):
        # Override global configuration with route-specific values.
        conf = route.config.get('pgsql') or {}
        autocommit = conf.get('autocommit', self.autocommit)
        autorollback = conf.get('autorollback', self.autorollback)
        keyword = conf.get('keyword', self.keyword)

        # Test if the original callback accepts a 'db' keyword.
        # Ignore it if it does not need a database handle.
        args = inspect.getfullargspec(route.callback)[0]
        if keyword not in args:
            return callback

        def wrapper(*args, **kwargs):
            try:
                if not self.con:
                    self.init_connection()

                cur = self.con.cursor()
            except HTTPResponse as e:
                raise HTTPError(500, "Database Error", e)
            except psycopg2.InterfaceError:
                self.init_connection()
                cur = self.con.cursor()

            # Add the connection handle as a keyword argument.
            kwargs[keyword] = cur

            try:
                rv = callback(*args, **kwargs)
                if autocommit:
                    self.con.commit()
                if autorollback:
                    self.con.rollback()
            except psycopg2.ProgrammingError as e:
                import traceback
                print(traceback.print_exc())
                self.con.rollback()
                raise HTTPError(500, "Database Error", e)
            except psycopg2.OperationalError as e:
                import traceback
                print(traceback.print_exc())
                try:
                    self.con.close()
                except:
                    pass
                self.con = None
                raise HTTPError(500, "Database Operational Error", e)
            except HTTPError as e:
                raise
            except HTTPResponse as e:
                if autocommit:
                    self.con.commit()
                raise
            return rv

        # Replace the route callback with the wrapped one.
        return wrapper

Plugin = PgSQLPlugin
