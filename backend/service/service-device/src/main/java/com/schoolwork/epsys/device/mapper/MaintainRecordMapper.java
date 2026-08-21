package com.schoolwork.epsys.device.mapper;


import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.schoolwork.epsys.model.device.MaintainRecord;
import com.schoolwork.epsys.device.knowledge.WorkOrderKnowledgeMetadata;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.Date;
import java.util.List;

/**
* @author 27959
* @description 针对表【maintain_record】的数据库操作Mapper
* @createDate 2025-04-07 08:24:12
* @Entity generator.domain.MaintainRecord
*/
public interface MaintainRecordMapper extends BaseMapper<MaintainRecord> {

    @Update("""
            UPDATE maintain_record
            SET miantain_id = #{workerId}, status = '维护中', version = version + 1
            WHERE id = #{orderId}
              AND tenant_id = #{tenantId}
              AND version = #{expectedVersion}
              AND miantain_id IS NULL
              AND status IN ('已通过', '待领取')
            """)
    int assignIfVersionMatches(@Param("orderId") Integer orderId,
                               @Param("workerId") Integer workerId,
                               @Param("tenantId") String tenantId,
                               @Param("expectedVersion") Integer expectedVersion);

    @Select("SELECT COUNT(*) FROM maintain_record WHERE miantain_id = #{workerId} AND status = '维护中'")
    int countActiveOrders(@Param("workerId") Integer workerId);

    @Select("""
            SELECT * FROM maintain_record
            WHERE status = '待领取'
              AND miantain_id IS NULL
              AND claim_deadline IS NOT NULL
              AND claim_deadline <= #{now}
            ORDER BY claim_deadline
            LIMIT #{limit}
            """)
    List<MaintainRecord> findExpiredClaimWindows(@Param("now") Date now, @Param("limit") int limit);

    @Select("""
            SELECT c.category_name AS deviceCategory, m.model_name AS deviceModel
            FROM maintain_record r
            LEFT JOIN deviceinstance i ON i.id = r.device_id
            LEFT JOIN devicemodel m ON m.id = i.model_id
            LEFT JOIN devicecategory c ON c.id = m.category_id
            WHERE r.id = #{orderId}
            """)
    WorkOrderKnowledgeMetadata selectKnowledgeMetadata(@Param("orderId") Integer orderId);
}

