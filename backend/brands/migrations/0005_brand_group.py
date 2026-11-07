from django.db import migrations, models


GROUPS = {
    "KABOOM77": ("SOLO - KABOOM", 1),
    "FF29": ("GROUP AK", 2),
    "CUNTWIN": ("GROUP U", 7),
    "COKESPIN": ("GROUP U", 8),
    "MATE29": ("GROUP U", 9),
    "SPINOO": ("GROUP U", 10),
    "BETCLUB6": ("GROUP U", 11),
}


def assign_groups(apps, schema_editor):
    Brand = apps.get_model("brands", "Brand")
    for name, (group, sort_order) in GROUPS.items():
        Brand.objects.filter(name=name).update(group=group, sort_order=sort_order)


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0004_bank_ledger_setting"),
    ]

    operations = [
        migrations.AddField(
            model_name="brand",
            name="group",
            field=models.CharField(
                blank=True,
                choices=[
                    ("SOLO - KABOOM", "SOLO - KABOOM"),
                    ("GROUP AK", "GROUP AK"),
                    ("GROUP U", "GROUP U"),
                ],
                max_length=32,
            ),
        ),
        migrations.RunPython(assign_groups, migrations.RunPython.noop),
    ]
