-- sql/create_cloudtrail_table.sql

CREATE EXTERNAL TABLE IF NOT EXISTS `irs_db`.`cloudtrail_logs` (
  eventTime STRING,
  eventName STRING,
  eventSource STRING,
  awsRegion STRING,
  sourceIPAddress STRING,
  userAgent STRING,
  requestParameters STRING,
  responseElements STRING,
  eventID STRING,
  eventType STRING,
  recipientAccountId STRING,
  sharedEventID STRING,
  vpcEndpointId STRING,
  eventVersion STRING,
  userIdentity STRUCT<
    type: STRING,
    principalId: STRING,
    arn: STRING,
    accountId: STRING,
    userName: STRING,
    sessionContext: STRUCT<
      attributes: STRUCT<
        mfaAuthenticated: STRING,
        creationDate: STRING
      >,
      sessionIssuer: STRUCT<
        type: STRING,
        principalId: STRING,
        arn: STRING,
        accountId: STRING,
        userName: STRING
      >
    >
  >,
  requestID STRING,
  errorCode STRING,
  errorMessage STRING,
  resources ARRAY<STRUCT<arn: STRING, accountId: STRING, type: STRING>>,
  readOnly STRING,
  additionalEventData STRING,
  serviceEventDetails STRING
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES (
  'ignore.malformed.json' = 'true'
)
STORED AS INPUTFORMAT 'org.apache.hadoop.mapred.TextInputFormat'
OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'
LOCATION 's3://cloudtrail-replay-bucket-897722691159/AWSLogs/897722691159/CloudTrail/' -- TODO: Update S3 location with actual bucket and account ID and region
TBLPROPERTIES (
  'projection.enabled' = 'true',
  'projection.year.type' = 'integer',
  'projection.year.range' = '2023-2025', -- Adjust as needed for 2 years back from current date
  'projection.year.digits' = '4',
  'projection.month.type' = 'integer',
  'projection.month.range' = '01-12',
  'projection.month.digits' = '2',
  'projection.day.type' = 'integer',
  'projection.day.range' = '01-31',
  'projection.day.digits' = '2',
  'storage.location.template' = 's3://cloudtrail-replay-bucket-897722691159/AWSLogs/897722691159/CloudTrail/${awsRegion}/${year}/${month}/${day}/',
  'classification' = 'json',
  'compressionType' = 'gzip'
);
