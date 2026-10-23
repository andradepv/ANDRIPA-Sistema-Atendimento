environment              = "production"
region                   = "sa-east-1"
domain_name              = "app.exemplo.com.br" # substitua pelo seu domínio
hosted_zone_id           = "ZXXXXXXXXXXXXX"     # substitua pela sua zona Route 53
api_image_tag            = "trocar-pelo-sha"    # o pipeline passa -var api_image_tag=<sha>
api_desired_count        = 2
api_max_count            = 6
db_instance_class        = "db.t4g.medium"
db_multi_az              = true
db_backup_retention_days = 14
alarm_email              = ""
