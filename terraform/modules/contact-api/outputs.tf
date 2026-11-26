output "function_url_domain" {
  description = "The function URL's host name, for the site's CloudFront distribution to send /api/feedback to."
  value       = trimsuffix(trimprefix(aws_lambda_function_url.handler.function_url, "https://"), "/")
}

output "function_name" {
  value = aws_lambda_function.handler.function_name
}

output "table_name" {
  description = "Where the messages are. Read them with: aws dynamodb scan --table-name <this>"
  value       = aws_dynamodb_table.messages.name
}
