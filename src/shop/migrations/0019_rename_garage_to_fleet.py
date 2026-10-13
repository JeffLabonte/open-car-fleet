import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0018_attachment_kind_default_blank'),
    ]

    operations = [
        # Rename the Garage domain to Fleet. The tables keep their explicit
        # db_table names until the AlterModelTable operations below, so the
        # RenameModel operations only update the migration state.
        migrations.RenameModel(
            old_name='Garage',
            new_name='Fleet',
        ),
        migrations.RenameModel(
            old_name='GarageMembership',
            new_name='FleetMembership',
        ),
        migrations.RenameModel(
            old_name='GarageInvitation',
            new_name='FleetInvitation',
        ),
        # Drop the old constraints before renaming the garage_id FK columns.
        # On SQLite, renaming a ForeignKey column remakes the whole table, and
        # the remake would fail while the constraints still reference the old
        # field name. The new constraints are re-added further below.
        migrations.RemoveConstraint(
            model_name='fleetmembership',
            name='garage_membership_valid_role',
        ),
        migrations.RemoveConstraint(
            model_name='fleetinvitation',
            name='uniq_pending_invitation_per_garage_email',
        ),
        # Rename the garage_id FK columns to fleet_id.
        migrations.RenameField(
            model_name='car',
            old_name='garage',
            new_name='fleet',
        ),
        migrations.RenameField(
            model_name='fleetmembership',
            old_name='garage',
            new_name='fleet',
        ),
        migrations.RenameField(
            model_name='fleetinvitation',
            old_name='garage',
            new_name='fleet',
        ),
        # Rename the explicit db_table values.
        migrations.AlterModelTable(
            name='Fleet',
            table='fleet',
        ),
        migrations.AlterModelTable(
            name='FleetMembership',
            table='fleet_membership',
        ),
        migrations.AlterModelTable(
            name='FleetInvitation',
            table='fleet_invitation',
        ),
        # Rename the auto-named indexes derived from the old table name.
        migrations.RenameIndex(
            model_name='fleetinvitation',
            new_name='fleet_invit_invited_70b689_idx',
            old_name='garage_invi_invited_0dcf69_idx',
        ),
        migrations.RenameIndex(
            model_name='fleetinvitation',
            new_name='fleet_invit_status_8e24d1_idx',
            old_name='garage_invi_status_8d2ef3_idx',
        ),
        # related_name updates (state-only, no schema change).
        migrations.AlterField(
            model_name='fleet',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='owned_fleets', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='fleet',
            name='members',
            field=models.ManyToManyField(related_name='fleets', through='shop.FleetMembership', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='fleetmembership',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='fleet_memberships', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='fleetinvitation',
            name='invited_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sent_fleet_invitations', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='fleetinvitation',
            name='accepted_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='accepted_fleet_invitations', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='fleetinvitation',
            name='declined_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='declined_fleet_invitations', to=settings.AUTH_USER_MODEL),
        ),
        # Re-add the constraints under their new names, now that the FK
        # columns are renamed.
        migrations.AddConstraint(
            model_name='fleetmembership',
            constraint=models.CheckConstraint(condition=models.Q(('role__in', ['owner', 'admin', 'mechanic', 'viewer'])), name='fleet_membership_valid_role'),
        ),
        migrations.AddConstraint(
            model_name='fleetinvitation',
            constraint=models.UniqueConstraint(condition=models.Q(('status', 'pending')), fields=('fleet', 'invited_email'), name='uniq_pending_invitation_per_fleet_email'),
        ),
        migrations.AlterUniqueTogether(
            name='fleetmembership',
            unique_together={('fleet', 'user')},
        ),
    ]
