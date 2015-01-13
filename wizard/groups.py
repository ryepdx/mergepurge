from openerp.osv import orm, fields

class wiz_groups(orm.TransientModel):
    _name = 'mergepurge.group.wizard'
    _columns = {}

    def generate_all(self, cr, uid, ids, context=None):
        self.pool.get('mergepurge.group').generate_all(cr, uid)
        return True

    def execute_all(self, cr, uid, ids, context=None):
        self.pool.get('mergepurge.group').execute_all(cr, uid)
        return True

wiz_groups()