output "zone_id" {
  value = aws_route53_zone.this.zone_id
}

output "name_servers" {
  description = "The four nameservers to set at the registrar."
  value       = aws_route53_zone.this.name_servers
}
