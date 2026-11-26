output "bucket_name" {
  description = "Upload the site here."
  value       = aws_s3_bucket.site.bucket
}

output "distribution_id" {
  description = "Needed to clear CloudFront's cache after an upload."
  value       = aws_cloudfront_distribution.site.id
}

output "distribution_arn" {
  description = "For letting an API origin's Lambda answer this distribution."
  value       = aws_cloudfront_distribution.site.arn
}

output "distribution_domain" {
  value = aws_cloudfront_distribution.site.domain_name
}
