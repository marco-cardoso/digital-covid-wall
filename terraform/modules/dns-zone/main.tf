# A public Route 53 hosted zone and the records that live at its top level.

resource "aws_route53_zone" "this" {
  name    = var.domain_name
  comment = "Managed by Terraform"

  # Deleting the zone would take the domain's DNS (website and email) down with it.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_route53_record" "this" {
  for_each = var.records

  zone_id = aws_route53_zone.this.zone_id
  name    = each.value.name == "" ? var.domain_name : "${each.value.name}.${var.domain_name}"
  type    = each.value.type
  ttl     = each.value.ttl
  records = each.value.values
}
