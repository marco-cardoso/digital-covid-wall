output "integrity_bucket" {
  description = "Where the deploy records the known-good list (manifest.json)."
  value       = aws_s3_bucket.integrity.bucket
}

output "integrity_bucket_arn" {
  value = aws_s3_bucket.integrity.arn
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "checker_function" {
  value = aws_lambda_function.checker.function_name
}
