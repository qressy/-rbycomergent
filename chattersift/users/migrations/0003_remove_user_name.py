from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_alter_user_id"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="name",
        ),
    ]
