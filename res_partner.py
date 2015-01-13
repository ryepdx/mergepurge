import string
from openerp.osv import osv, fields

class res_partner(osv.osv):
    _inherit = "res.partner"

    def _get_mergepurge_key(self, cr, uid, ids, field_name, args, context=None):
        keys = {}
        remove_punctuation_map = dict((ord(char), None) for char in string.punctuation)
        format_str = lambda x: unicode(x).strip().upper().translate(remove_punctuation_map)

        for partner in self.browse(cr, uid, ids, context=context):
            keys[partner.id] = "%s,%s,%s,%s,%s" % tuple(map(format_str, [
                partner.company_id.id if partner.company_id else '',
                partner.name, partner.street, partner.street2, partner.zip
            ]))

        return keys

    _columns = {
        'assoc_ids': fields.one2many('mergepurge.assoc', 'partner_id', 'Scheduled Merges'),
        #'mergepurge_ids': fields.related('assoc_ids', 'mergepurge_id', type='one2many', string="Merge Groups"),
        'mergepurge_key': fields.function(_get_mergepurge_key, type='text', string="Merge Key"),
        'last_merge': fields.datetime('Last Merge')
    }

res_partner()


class mergepurge_assoc(osv.osv):
    _name = "mergepurge.assoc"

    _columns = {
        'mergepurge_id': fields.many2one('mergepurge.group', 'Merge Group', readonly=True, required=True),
        'mergepurge_key': fields.related('partner_id', 'mergepurge_key', type='text', string='Merge Key'),
        'partner_id': fields.many2one('res.partner', "Customer", domain=[('customer','=', True)], required=True)
    }

    def name_get(self, cr, uid, ids, context=None):
        return [(record['id'], record['mergepurge_key'])
                for record in self.read(cr, uid, ids, ['mergepurge_key'], context=context)]

mergepurge_assoc()


class mergepurge_group(osv.osv):
    _name = 'mergepurge.group'

    def _get_oldest(self, cr, uid, ids, field_name, args, context=None, reverse=False):
        values = {}

        for group in self.browse(cr, uid, ids, context=context):
            values[group.id] = None

            for partner in sorted([a.partner_id for a in group.assoc_ids], key=lambda o: o.id, reverse=reverse):
                if hasattr(partner, field_name) and getattr(partner, field_name):
                    values[group.id] = getattr(partner, field_name)
                    if hasattr(values[group.id], 'id'):
                        values[group.id] = values[group.id].id

                    break

        return values

    def _get_newest(self, cr, uid, ids, field_name, args, context=None):
        return self._get_oldest(cr, uid, ids, field_name, args, context=context, reverse=True)

    def _get_member_count(self, cr, uid, ids, field_name, arg, context):
        return dict([(g.id, len(g.assoc_ids)) for g in self.browse(cr, uid, ids, context=context)])

    def _get_assoc_group_id(assoc_pool, cr, uid, ids, context=None):
        return [assoc.mergepurge_id.id for assoc in assoc_pool.browse(cr, uid, ids)]

    _columns = {
        'name': fields.function(_get_newest, type='char', string='Name', method=True),
        'ref': fields.function(_get_oldest, type='char', string='Reference', method=True),
        'date': fields.function(_get_oldest, type='date', string='Date', method=True),
        'street': fields.function(_get_newest, type='char', string='Street', method=True),
        'street2': fields.function(_get_newest, type='char', string='Street2', method=True),
        'zip': fields.function(_get_newest, type='char', string='Zip', method=True),
        'city': fields.function(_get_newest, type='char', string='City', method=True),
        'state_id': fields.function(_get_newest, type='many2one', relation='res.country.state', string='State', method=True),
        'country_id': fields.function(_get_newest, type='many2one', relation='res.country', string='Country', method=True),
        'email': fields.function(_get_newest, type='char', string='Email', method=True),
        'phone': fields.function(_get_newest, type='char', string='Phone', method=True),
        'fax': fields.function(_get_newest, type='char', string='Fax', method=True),
        'mobile': fields.function(_get_newest, type='char', string='Mobile', method=True),
        'mergepurge_key': fields.text('Merge Key', readonly=True),
        'assoc_ids': fields.one2many('mergepurge.assoc', 'mergepurge_id', 'Customers'),
        'member_count': fields.function(_get_member_count, type='integer', method=True, store={
            'mergepurge.assoc': (_get_assoc_group_id, ['mergepurge_id'], 10)
        }, string="# Customers")
    }
    _sql_constraints = [
        ('mergepurge_group_key_uniq', 'unique(mergepurge_key)', "Merge Key")
    ]

    def get_chunk(self, cr, uid, chunk_size, from_date=None, context=None):
        partner_pool = self.pool.get("res.partner")
        criteria = [("last_merge", ">=", from_date)] if from_date else []
        return partner_pool.search(cr, uid, criteria, limit=chunk_size, context=context)

    def execute(self, cr, uid, ids, context=None):
        assoc_pool = self.pool.get('mergepurge.assoc')
        partner_pool = self.pool.get("res.partner")
        field_names = ['name', 'ref', 'date', 'street', 'street2', 'city', 'state_id', 'zip', 'country_id',
                       'email', 'phone', 'fax', 'mobile']

        for group in self.browse(cr, uid, ids, context=context):
            if not group.assoc_ids:
                continue

            partners = sorted([assoc.partner_id for assoc in group.assoc_ids], key=lambda o: o.id)
            partner_pool.write(cr, uid, partners[0].id, dict(
                [(field_name, getattr(group, field_name)) for field_name in field_names]
            ))

            # Update properties to point to oldest partner.
            cr.execute(
                "UPDATE ir_property SET res_id=%s WHERE res_id in %s",
                ('res.partner,' + str(partners[0].id), tuple(['res.partner,' + str(p.id) for p in partners[1:]]))
            )

            # Update fields to point to oldest partner.
            field_pool = self.pool.get('ir.model.fields')

            for field in field_pool.browse(cr, uid, field_pool.search(
                    cr, uid, [('relation', '=', 'res.partner'), ('ttype', '=', 'many2one')])):

                table_name = field.model.replace('.', '_')
                cr.execute("""
                    SELECT column_name FROM information_schema.tables AS t
                    LEFT JOIN information_schema.columns AS c
                    ON t.table_name=c.table_name AND t.table_type!='VIEW'
                    WHERE c.table_name=%s AND c.column_name=%s""", (table_name, field.name))

                if cr.rowcount > 0:
                    cr.execute("UPDATE " + table_name + " SET " + field.name + "=%s WHERE " + field.name + " IN %s",
                               (partners[0].id, tuple([p.id for p in partners[1:]])))

            assoc_pool.unlink(cr, uid, assoc_pool.search(cr, uid, [('partner_id', 'in', [p.id for p in partners])]))
            partner_pool.unlink(cr, uid, [p.id for p in partners[1:]])
            cr.execute("DELETE FROM mergepurge_group WHERE id NOT IN (SELECT mergepurge_id FROM mergepurge_assoc)")

        return True

    def execute_chunk(self, cr, uid, *args, **kwargs):
        self.execute(cr, uid, self.get_chunk(cr, uid, *args, **kwargs))

    def execute_all(self, cr, uid, *args):
        self.execute(cr, uid, self.search())

    def generate_chunk(self, cr, uid, *args, **kwargs):
        return self.generate_all(cr, uid, ids=self.get_chunk(cr, uid, *args, **kwargs))

    def generate_all(self, cr, uid, *args, **kwargs):
        assoc_pool = self.pool.get('mergepurge.assoc')
        group_pool = self.pool.get('mergepurge.group')
        partner_pool = self.pool.get("res.partner")
        customer_criteria = kwargs.get('criteria', [("customer", "=", True)])

        if 'ids' in kwargs or args:
            customer_criteria.append(("id", "in", args[0] if args else kwargs.get("ids", [])))

        force_grouping = False
        if 'force_grouping' in kwargs or len(args) > 1:
            force_grouping = args[1] if len(args) > 1 else kwargs.get("force_grouping", [])

        if 'max_id' in kwargs:
            customer_criteria.append(("id", "<=", kwargs.get("max_id")))

        if 'min_id' in kwargs:
            customer_criteria.append(("id", ">=", kwargs.get("min_id")))

        group_ids = {}

        sequence_pool = self.pool.get('ir.sequence') if force_grouping else None

        for partner in partner_pool.browse(cr, uid, partner_pool.search(cr, uid, customer_criteria)):
            if force_grouping:
                group_search = [group_ids['forced']] if 'forced' in group_ids else None
            elif partner.mergepurge_key in group_ids:
                group_search = [group_ids[partner.mergepurge_key]]
            else:
                group_search = group_pool.search(cr, uid, [("mergepurge_key", "=", partner.mergepurge_key)])

            if group_search:
                group_id = group_search[0]
            else:
                key = partner.mergepurge_key if not sequence_pool else sequence_pool.get(cr, uid, 'mergepurge.group')
                group_id = group_pool.create(cr, uid, {'mergepurge_key': key}, context=kwargs.get("context"))
                group_ids['forced' if force_grouping else partner.mergepurge_key] = group_id

            existing_assoc = assoc_pool.search(cr, uid, [("partner_id", "=", partner.id)])

            if not existing_assoc:
                assoc_pool.create(cr, uid, {"mergepurge_id": group_id, "partner_id": partner.id}, kwargs.get("context"))

        return group_ids.values()

    def generate_res_partner_action(self, cr, uid, *args, **kwargs):
        group_ids = self.generate_all(cr, uid, *args, **kwargs)
        ref_pool = self.pool.get('ir.model.data')
        return {
            'id': ref_pool.get_object_reference(cr, uid, 'mergepurge', 'action_mergepurge_group')[1],
            'view_mode': 'form',
            'view_id': ref_pool.get_object_reference(cr, uid, 'mergepurge', 'form_group')[1],
            'view_type': 'form',
            'res_model': 'mergepurge.group',
            'type': 'ir.actions.act_window',
            'target': 'current',
            'res_id': group_ids[0]
        }

    def execute_mergepurge_group_action(self, cr, uid, *args, **kwargs):
        self.execute(cr, uid, *args, **kwargs)
        ref_pool = self.pool.get('ir.model.data')
        return {
            'id': ref_pool.get_object_reference(cr, uid, 'mergepurge', 'action_mergepurge_group')[1],
            'view_mode': 'tree',
            'view_id': ref_pool.get_object_reference(cr, uid, 'mergepurge', 'tree_group')[1],
            'view_type': 'tree',
            'res_model': 'mergepurge.group',
            'type': 'ir.actions.act_window',
            'target': 'current'
        }

    def name_get(self, cr, uid, ids, context=None):
        return [(record['id'], record['mergepurge_key'])
                for record in self.read(cr, uid, ids, ['mergepurge_key'], context=context)]

    def cron_merge_and_purge(self, cr, uid, context=None):
        ids = self.search(cr, uid, [("address_validated","=",False)])
        pool_names = dict(self._method_get(cr, uid, context=context).keys())

        if not pool_names:
            return

        self.normalize_addresses(
            cr, uid, ids, failover_pools=[self.pool.get(name) for name in pool_names], context=context)

        group_pool = self.pool.get("mergepurge.group")
        group_ids = group_pool.generate_all(cr, uid)
        group_pool.execute(cr, uid, group_ids)

mergepurge_group()
