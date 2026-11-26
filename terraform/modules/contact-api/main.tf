# The contact form's backend: a Lambda that stores each message in a DynamoDB table.
#
# The function has a URL, but it answers only requests that CloudFront has signed (origin access control), so the
# form reaches it at /api/feedback on the site's own domain and nothing can call it around CloudFront. The site's
# distribution is given the URL's domain (see the static-site module's `api` variable); this module lets that
# distribution, and only it, invoke the function.

locals {
  function_name = "${var.name}-contact-api"
}

# ---- Where the messages are kept ---------------------------------------------------------------------------------

resource "aws_dynamodb_table" "messages" {
  name         = "${var.name}-contact-messages"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  # Messages from the public are not something to lose to a stray destroy; turn this off first to remove the table.
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = var.tags
}

# ---- The function ------------------------------------------------------------------------------------------------

data "archive_file" "handler" {
  type        = "zip"
  source_file = "${path.module}/lambda/handler.py"
  # Under .terraform/, which git ignores, in whichever environment applies this.
  output_path = "${path.root}/.terraform/build/${local.function_name}.zip"
}

resource "aws_cloudwatch_log_group" "handler" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "handler" {
  name               = local.function_name
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

# Add messages and write its own logs: nothing else, not even reading the messages back.
data "aws_iam_policy_document" "handler" {
  statement {
    sid       = "StoreMessages"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.messages.arn]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.handler.arn}:*"]
  }
}

resource "aws_iam_role_policy" "handler" {
  name   = "store-messages"
  role   = aws_iam_role.handler.id
  policy = data.aws_iam_policy_document.handler.json
}

resource "aws_lambda_function" "handler" {
  function_name    = local.function_name
  description      = "Stores messages sent through the ${var.name} contact form"
  role             = aws_iam_role.handler.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = data.archive_file.handler.output_path
  source_code_hash = data.archive_file.handler.output_base64sha256
  memory_size      = 128
  timeout          = 5

  # A cap on how many messages are handled at once, so a flood of requests cannot run up the bill. Null leaves it
  # to the account's pool (a new account may not have room to reserve any).
  reserved_concurrent_executions = var.max_concurrency

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.messages.name
    }
  }

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.handler, aws_iam_role_policy.handler]
}

resource "aws_lambda_function_url" "handler" {
  function_name      = aws_lambda_function.handler.function_name
  authorization_type = "AWS_IAM"
}

# CloudFront signs its requests to the URL; Lambda wants both of these permissions for that.
resource "aws_lambda_permission" "cloudfront_url" {
  statement_id           = "CloudFrontInvokeFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.handler.function_name
  principal              = "cloudfront.amazonaws.com"
  source_arn             = var.cloudfront_distribution_arn
  function_url_auth_type = "AWS_IAM"
}

resource "aws_lambda_permission" "cloudfront_invoke" {
  statement_id             = "CloudFrontInvokeFunction"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.handler.function_name
  principal                = "cloudfront.amazonaws.com"
  source_arn               = var.cloudfront_distribution_arn
  invoked_via_function_url = true
}
