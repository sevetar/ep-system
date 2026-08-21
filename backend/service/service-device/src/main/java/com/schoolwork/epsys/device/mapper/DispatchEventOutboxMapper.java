package com.schoolwork.epsys.device.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.schoolwork.epsys.model.device.DispatchEventOutbox;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.Date;
import java.util.List;

public interface DispatchEventOutboxMapper extends BaseMapper<DispatchEventOutbox> {

    @Select("""
            SELECT * FROM dispatch_event_outbox
            WHERE (publish_status IN ('PENDING', 'FAILED') AND next_retry_at <= #{now})
               OR (publish_status = 'PUBLISHING' AND updated_at <= #{staleBefore})
            ORDER BY id
            LIMIT #{limit}
            """)
    List<DispatchEventOutbox> findPublishable(@Param("now") Date now,
                                              @Param("staleBefore") Date staleBefore,
                                              @Param("limit") int limit);

    @Update("""
            UPDATE dispatch_event_outbox
            SET publish_status = 'PUBLISHING', updated_at = NOW()
            WHERE id = #{id}
              AND ((publish_status IN ('PENDING', 'FAILED') AND next_retry_at <= #{now})
                OR (publish_status = 'PUBLISHING' AND updated_at <= #{staleBefore}))
            """)
    int claimForPublishing(@Param("id") Long id,
                           @Param("now") Date now,
                           @Param("staleBefore") Date staleBefore);

    @Update("""
            UPDATE dispatch_event_outbox
            SET publish_status = 'PUBLISHED', published_at = NOW(), last_error = NULL, updated_at = NOW()
            WHERE id = #{id} AND publish_status = 'PUBLISHING'
            """)
    int markPublished(@Param("id") Long id);

    @Update("""
            UPDATE dispatch_event_outbox
            SET publish_status = 'FAILED', retry_count = retry_count + 1,
                next_retry_at = #{nextRetryAt}, last_error = #{lastError}, updated_at = NOW()
            WHERE id = #{id} AND publish_status = 'PUBLISHING'
            """)
    int markFailed(@Param("id") Long id,
                   @Param("nextRetryAt") Date nextRetryAt,
                   @Param("lastError") String lastError);
}
