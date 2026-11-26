# Watches a static site for tampering and raises the alarm by email and SMS.
#
# Each deploy records a known-good list (every file's path, SHA-256, MD5 and size) in a private, versioned
# integrity bucket. A Lambda (lambda/handler.py) then checks the site against it:
#
# - at once, on every write or delete in the site's bucket (S3 -> EventBridge);
# - every few minutes, all of it: every object in the bucket, and the live site over HTTPS as visitors get it
#   (the page and all it loads, the dashboard data, a rotating sample of the rest), which also catches a changed
#   CloudFront origin, DNS or certificate;
# - whenever the known-good list itself is rewritten, with an email saying so.
#
# Alerts go to an SNS topic: email gets everything, SMS only the alarms. A CloudWatch alarm also fires if the
# scheduled checks stop, or the checker keeps failing.

data "aws_caller_identity" "current" {}

locals {
  function_name    = "${var.name}-site-monitor"
  integrity_bucket = "${var.name}-integrity-${data.aws_caller_identity.current.account_id}"
}

# ---- The known-good list ------------------------------------------------------------------------------------------

resource "aws_s3_bucket" "integrity" {
  bucket = local.integrity_bucket
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "integrity" {
  bucket                  = aws_s3_bucket.integrity.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "integrity" {
  bucket = aws_s3_bucket.integrity.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Every list ever recorded is kept a year: what the site should have looked like at any time.
resource "aws_s3_bucket_versioning" "integrity" {
  bucket = aws_s3_bucket.integrity.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "integrity" {
  bucket     = aws_s3_bucket.integrity.id
  depends_on = [aws_s3_bucket_versioning.integrity]

  rule {
    id     = "expire-old-lists"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 365
    }
  }
}

# Both buckets report their changes to EventBridge.
resource "aws_s3_bucket_notification" "site" {
  bucket      = var.site_bucket
  eventbridge = true
}

resource "aws_s3_bucket_notification" "integrity" {
  bucket      = aws_s3_bucket.integrity.id
  eventbridge = true
}

# ---- Where the alerts go ------------------------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${var.name}-site-alerts"
  tags = var.tags
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Texts only for the alarms: the checker's "alert" messages, and CloudWatch's (which carry no severity).
resource "aws_sns_topic_subscription" "sms" {
  count = var.alert_phone == null ? 0 : 1

  topic_arn     = aws_sns_topic.alerts.arn
  protocol      = "sms"
  endpoint      = var.alert_phone
  filter_policy = jsonencode({ severity = ["alert", { exists = false }] })
}

# ---- The checker --------------------------------------------------------------------------------------------------

# The two source files only (not the tests, nor any __pycache__ left by running them).
data "archive_file" "checker" {
  type        = "zip"
  output_path = "${path.root}/.terraform/build/${local.function_name}.zip"

  source {
    filename = "handler.py"
    content  = file("${path.module}/lambda/handler.py")
  }

  source {
    filename = "checker.py"
    content  = file("${path.module}/lambda/checker.py")
  }
}

resource "aws_cloudwatch_log_group" "checker" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = 30
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

resource "aws_iam_role" "checker" {
  name               = local.function_name
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

# Read-only on the site; on the integrity bucket, read the list and keep its own small state file.
data "aws_iam_policy_document" "checker" {
  statement {
    sid       = "ListSite"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.site_bucket}"]
  }

  statement {
    sid       = "ReadList"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.integrity.arn}/manifest.json", "${aws_s3_bucket.integrity.arn}/state/*"]
  }

  # Without ListBucket, S3 answers a missing list with AccessDenied rather than NoSuchKey.
  statement {
    sid       = "ListIntegrity"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.integrity.arn]
  }

  statement {
    sid       = "KeepState"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.integrity.arn}/state/*"]
  }

  statement {
    sid       = "Alert"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }

  statement {
    sid       = "Heartbeat"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["CovidWall/SiteIntegrity"]
    }
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.checker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "checker" {
  name   = "check-site"
  role   = aws_iam_role.checker.id
  policy = data.aws_iam_policy_document.checker.json
}

resource "aws_lambda_function" "checker" {
  function_name    = local.function_name
  description      = "Checks ${var.site_url} against its known-good list"
  role             = aws_iam_role.checker.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = data.archive_file.checker.output_path
  source_code_hash = data.archive_file.checker.output_base64sha256
  memory_size      = 256
  timeout          = 120

  # A few at once: a deploy's thousands of upload events drain quickly, and the alert state stays simple.
  reserved_concurrent_executions = 5

  environment {
    variables = {
      SITE_NAME        = var.site
      SITE_URL         = var.site_url
      SITE_BUCKET      = var.site_bucket
      INTEGRITY_BUCKET = aws_s3_bucket.integrity.bucket
      TOPIC_ARN        = aws_sns_topic.alerts.arn
    }
  }

  tags       = var.tags
  depends_on = [aws_cloudwatch_log_group.checker, aws_iam_role_policy.checker]
}

# ---- When it runs -------------------------------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${local.function_name}-schedule"
  description         = "Checks ${var.site_url} in full"
  schedule_expression = "rate(${var.check_every_minutes} minutes)"
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "schedule" {
  rule  = aws_cloudwatch_event_rule.schedule.name
  arn   = aws_lambda_function.checker.arn
  input = jsonencode({ mode = "scheduled" })
}

resource "aws_cloudwatch_event_rule" "site_changes" {
  name        = "${local.function_name}-site-changes"
  description = "Every write or delete in the ${var.site} site's bucket"
  tags        = var.tags

  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created", "Object Deleted"]
    detail        = { bucket = { name = [var.site_bucket] } }
  })
}

resource "aws_cloudwatch_event_target" "site_changes" {
  rule = aws_cloudwatch_event_rule.site_changes.name
  arn  = aws_lambda_function.checker.arn
}

# Only the list itself: the checker's own state file lives in the same bucket and must not set it off.
resource "aws_cloudwatch_event_rule" "list_changes" {
  name        = "${local.function_name}-list-changes"
  description = "The ${var.site} site's known-good list is rewritten or deleted"
  tags        = var.tags

  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created", "Object Deleted"]
    detail = {
      bucket = { name = [aws_s3_bucket.integrity.bucket] }
      object = { key = ["manifest.json"] }
    }
  })
}

resource "aws_cloudwatch_event_target" "list_changes" {
  rule = aws_cloudwatch_event_rule.list_changes.name
  arn  = aws_lambda_function.checker.arn
}

resource "aws_lambda_permission" "events" {
  for_each = {
    schedule     = aws_cloudwatch_event_rule.schedule.arn
    site_changes = aws_cloudwatch_event_rule.site_changes.arn
    list_changes = aws_cloudwatch_event_rule.list_changes.arn
  }

  statement_id  = "EventBridge-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.checker.function_name
  principal     = "events.amazonaws.com"
  source_arn    = each.value
}

# ---- Watching the watcher -----------------------------------------------------------------------------------------

# No scheduled check for three periods in a row: the monitor has stopped (or been stopped).
resource "aws_cloudwatch_metric_alarm" "stopped" {
  alarm_name          = "${local.function_name}-stopped"
  alarm_description   = "The ${var.site} site monitor has not completed a check in ${3 * var.check_every_minutes} minutes."
  namespace           = "CovidWall/SiteIntegrity"
  metric_name         = "ScheduledChecks"
  dimensions          = { Site = var.site }
  statistic           = "Sum"
  period              = var.check_every_minutes * 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = var.tags
}

resource "aws_cloudwatch_metric_alarm" "failing" {
  alarm_name          = "${local.function_name}-failing"
  alarm_description   = "The ${var.site} site monitor's checker is failing."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.checker.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = var.tags
}
