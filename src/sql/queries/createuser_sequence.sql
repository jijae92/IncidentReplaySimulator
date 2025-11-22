WITH c AS (
  SELECT from_iso8601_timestamp(eventTime) AS et, eventName, userIdentity.arn AS actor_arn,
         json_extract_scalar(requestParameters, '$.userName') AS target_user,
         sourceIPAddress AS src_ip, userAgent
  FROM irs_db.cloudtrail_logs
  WHERE eventName IN ('CreateUser','AttachUserPolicy','PutUserPolicy','CreateAccessKey')
    AND from_iso8601_timestamp(eventTime) BETWEEN TIMESTAMP :from_ts AND TIMESTAMP :to_ts
)
SELECT actor_arn, any_value(src_ip) AS src_ip,
       min(et) AS first_event_time, max(et) AS last_event_time,
       max(CASE WHEN eventName='CreateUser' THEN 1 ELSE 0 END) +
       max(CASE WHEN eventName IN ('AttachUserPolicy','PutUserPolicy') THEN 1 ELSE 0 END) +
       max(CASE WHEN eventName='CreateAccessKey' THEN 1 ELSE 0 END) AS sequence_score,
       max(target_user) AS target_user
FROM c
GROUP BY actor_arn
HAVING sequence_score >= 2
ORDER BY last_event_time DESC
LIMIT 1000;