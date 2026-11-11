"""
Database router para dirigir los modelos de iahelp a la base de datos default.
"""


class IahelpRouter:
    """
    Enruta las operaciones de los modelos de la app iahelp
    a la base de datos 'default'.
    """

    app_label = "iahelp"
    db_name = "default"

    def db_for_read(self, model, **hints):
        return self.db_name

    def db_for_write(self, model, **hints):
        return self.db_name

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return True
