environment              = "development"
region                   = "sa-east-1"
domain_name              = "dev.exemplo.com.br" # substitua pelo seu domínio
hosted_zone_id           = "ZXXXXXXXXXXXXX"     # substitua pela sua zona Route 53
api_image_tag            = "trocar-pelo-sha"    # o pipeline passa -var api_image_tag=<sha>
api_desired_count        = 1
api_max_count            = 2
db_instance_class        = "db.t4g.micro"
db_multi_az              = false
db_backup_retention_days = 3
alarm_email              = ""
