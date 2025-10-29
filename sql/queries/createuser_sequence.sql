-- Detect IAM CreateUser escalation sequences within a 15 minute window.

WITH raw_logs AS (
    SELECT json_parse(json_data) as parsed_json
    FROM irs_db.replay_events_raw
),
unnested_records AS (
    SELECT
        t AS record_json
    FROM raw_logs
    CROSS JOIN UNNEST(json_extract_array(parsed_json, '$.Records')) AS t
),
-- 1단계: 모든 필드를 JSON 타입으로 통일 추출
json_extracted_records AS (
  SELECT
    json_extract(record_json, '$.eventVersion')                AS eventversion_json,
    json_extract(record_json, '$.userIdentity')                AS useridentity_json,
    json_extract(record_json, '$.eventTime')                   AS eventtime_json,
    json_extract(record_json, '$.eventSource')                 AS eventsource_json,
    json_extract(record_json, '$.eventName')                   AS eventname_json,
    json_extract(record_json, '$.sourceIPAddress')             AS sourceipaddress_json,
    json_extract(record_json, '$.awsRegion')                   AS awsregion_json,
    json_extract(record_json, '$.requestParameters')           AS requestparameters_json,
    json_extract(record_json, '$.responseElements')            AS responseelements_json,
    json_extract(record_json, '$.additionalEventData')         AS additionaleventdata_json,
    json_extract(record_json, '$.resources')                   AS resources_json
  FROM unnested_records
),

-- 2단계: 필요한 스칼라 값으로 변환 + 널/형태 다양성에 대비한 coalesce
base AS (
  SELECT
    try(json_extract_scalar(eventtime_json, '$'))      AS event_ts_txt,
    try(from_iso8601_timestamp(json_extract_scalar(eventtime_json, '$'))) AS event_ts,
    try(json_extract_scalar(eventname_json, '$'))      AS event_name,
    try(json_extract_scalar(eventsource_json, '$'))    AS event_source,
    -- actor_arn은 여러 형태 대비(AssumeRole 등)
    coalesce(
      try(json_extract_scalar(cast(useridentity_json AS VARCHAR), '$.arn')),
      try(json_extract_scalar(cast(useridentity_json AS VARCHAR), '$.sessionContext.sessionIssuer.arn')),
      try(json_extract_scalar(cast(requestparameters_json AS VARCHAR), '$.roleArn')),
      try(json_extract_scalar(cast(additionaleventdata_json AS VARCHAR), '$.CallerArn'))
    )                                                  AS actor_arn,
    try(json_extract_scalar(sourceipaddress_json, '$')) AS source_ip,
    try(json_extract_scalar(awsregion_json, '$'))       AS aws_region,
    -- 아래 둘은 그대로 JSON 보존(후속 단계에서 필요시 scalar 변환)
    requestparameters_json,
    responseelements_json
  FROM json_extracted_records
  WHERE
    try(json_extract_scalar(awsregion_json, '$')) = 'ap-northeast-2'
    AND try(from_iso8601_timestamp(json_extract_scalar(eventtime_json, '$')))
          BETWEEN from_iso8601_timestamp(:from_ts) AND from_iso8601_timestamp(:to_ts)
      AND try(json_extract_scalar(eventname_json, '$')) IN ('CreateUser', 'AttachUserPolicy', 'PutUserPolicy', 'CreateAccessKey')
),
create_user AS (
    SELECT
        event_ts,
        actor_arn,
        requestparameters_json AS requestparameters,
        responseelements_json AS responseelements,
        source_ip AS sourceipaddress,
        'IRS-ReplaySimulator/1.0' AS useragent, -- Placeholder, as useragent is not directly extracted in the new base CTE
        coalesce(
            json_extract_scalar(requestparameters_json, '$.userName'),
            json_extract_scalar(responseelements_json, '$.userName'),
            json_extract_scalar(responseelements_json, '$.user.userName')
        ) AS target_user
    FROM base
    WHERE event_name = 'CreateUser'
),
policy_events AS (
    SELECT
        event_ts,
        actor_arn
    FROM base
    WHERE event_name IN ('AttachUserPolicy', 'PutUserPolicy')
),
access_key_events AS (
    SELECT
        event_ts,
        actor_arn
    FROM base
    WHERE event_name = 'CreateAccessKey'
),
aggregated AS (
    SELECT
        cu.actor_arn,
        coalesce(cu.target_user, 'unknown') AS target_user,
        cu.event_ts AS create_user_ts,
        max(pe.event_ts) AS policy_ts,
        max(ak.event_ts) AS access_key_ts,
        cu.sourceipaddress AS src_ip,
        cu.useragent AS user_agent
    FROM create_user cu
    LEFT JOIN policy_events pe
      ON pe.actor_arn = cu.actor_arn
     AND pe.event_ts BETWEEN cu.event_ts - INTERVAL '15' MINUTE AND cu.event_ts + INTERVAL '15' MINUTE
    LEFT JOIN access_key_events ak
      ON ak.actor_arn = cu.actor_arn
     AND ak.event_ts BETWEEN cu.event_ts - INTERVAL '15' MINUTE AND cu.event_ts + INTERVAL '15' MINUTE
    GROUP BY
        cu.actor_arn,
        cu.target_user,
        cu.event_ts,
        cu.sourceipaddress,
        cu.useragent
)
SELECT
    actor_arn,
    target_user,
    date_format(create_user_ts, '%Y-%m-%dT%H:%i:%sZ') AS first_event_time,
    date_format(
        greatest(
            create_user_ts,
            coalesce(policy_ts, create_user_ts),
            coalesce(access_key_ts, create_user_ts)
        ),
        '%Y-%m-%dT%H:%i:%sZ'
    ) AS last_event_time,
    src_ip,
    user_agent,
    1.0
        + IF(policy_ts IS NOT NULL, 0.5, 0.0)
        + IF(access_key_ts IS NOT NULL, 0.3, 0.0) AS sequence_score
FROM aggregated
ORDER BY first_event_time DESC;