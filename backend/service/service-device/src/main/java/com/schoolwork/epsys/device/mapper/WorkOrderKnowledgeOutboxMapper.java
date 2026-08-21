package com.schoolwork.epsys.device.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.schoolwork.epsys.model.device.WorkOrderKnowledgeOutbox;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.Date;
import java.util.List;

public interface WorkOrderKnowledgeOutboxMapper extends BaseMapper<WorkOrderKnowledgeOutbox> {

    @Select("""
            SELECT * FROM work_order_knowledge_outbox
            WHERE (publish_status IN ('PENDING', 'FAILED') AND next_retry_at <= #{now})
               OR (publish_status = 'PUBLISHING' AND updated_at <= #{staleBefore})
            ORDER BY id
            LIMIT #{limit}
            """)
    List<WorkOrderKnowledgeOutbox> findPublishable(@Param("now") Date now,
                                                   @Param("staleBefore") Date staleBefore,
                                                   @Param("limit") int limit);

    @Update("""
            UPDATE work_order_knowledge_outbox
            SET publish_status = 'PUBLISHING', updated_at = NOW()
            WHERE id = #{id}
              AND ((publish_status IN ('PENDING', 'FAILED') AND next_retry_at <= #{now})
                OR (publish_status = 'PUBLISHING' AND updated_at <= #{staleBefore}))
            """)
    int claimForPublishing(@Param("id") Long id,
                           @Param("now") Date now,
                           @Param("staleBefore") Date staleBefore);

    @Update("""
            UPDATE work_order_knowledge_outbox
            SET publish_status = 'PUBLISHED', published_at = NOW(), last_error = NULL, updated_at = NOW()
            WHERE id = #{id} AND publish_status = 'PUBLISHING'
            """)
    int markPublished(@Param("id") Long id);

    @Update("""
            UPDATE work_order_knowledge_outbox
            SET publish_status = 'FAILED', retry_count = retry_count + 1,
                next_retry_at = #{nextRetryAt}, last_error = #{lastError}, updated_at = NOW()
            WHERE id = #{id} AND publish_status = 'PUBLISHING'
            """)
    int markFailed(@Param("id") Long id,
                   @Param("nextRetryAt") Date nextRetryAt,
                   @Param("lastError") String lastError);

    @Select("SELECT * FROM work_order_knowledge_outbox WHERE event_id = #{eventId} LIMIT 1")
    WorkOrderKnowledgeOutbox findByEventId(@Param("eventId") String eventId);

    @Update("""
            UPDATE work_order_knowledge_outbox
            SET ingestion_status = #{status}, chunk_count = #{chunkCount},
                quality_score = #{qualityScore}, quality_issues = #{qualityIssues},
                ingestion_error = #{error},
                ingested_at = CASE WHEN #{status} IN ('indexed', 'skipped') THEN NOW() ELSE ingested_at END,
                updated_at = NOW()
            WHERE event_id = #{eventId}
            """)
    int markIngestionResult(@Param("eventId") String eventId,
                            @Param("status") String status,
                            @Param("chunkCount") int chunkCount,
                            @Param("qualityScore") int qualityScore,
                            @Param("qualityIssues") String qualityIssues,
                            @Param("error") String error);
}
