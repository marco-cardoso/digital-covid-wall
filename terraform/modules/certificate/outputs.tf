output "certificate_arn" {
  description = "The issued certificate (available once validation has finished)."
  value       = aws_acm_certificate_validation.this.certificate_arn
}
