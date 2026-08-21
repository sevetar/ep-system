package com.schoolwork.epsys.acl.mapper;


import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.schoolwork.epsys.model.acl.Devicetousers;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
* @author 27959
* @description 针对表【devicetousers】的数据库操作Mapper
* @createDate 2025-05-06 15:17:11
* @Entity pojo.message.Devicetousers
*/
public interface DevicetousersMapper extends BaseMapper<Devicetousers> {

    @Select("SELECT * FROM devicetousers WHERE device_id = #{deviceId} LIMIT 1")
    Devicetousers findByDeviceId(@Param("deviceId") Integer deviceId);

    @Update("""
            UPDATE devicetousers
            SET binding_status = #{targetStatus}, request_id = #{newRequestId},
                failure_reason = NULL, updated_at = NOW()
            WHERE id = #{id} AND binding_status = #{expectedStatus}
            """)
    int transition(@Param("id") Integer id,
                   @Param("expectedStatus") String expectedStatus,
                   @Param("targetStatus") String targetStatus,
                   @Param("newRequestId") String newRequestId);

    @Update("""
            UPDATE devicetousers
            SET binding_status = #{targetStatus}, failure_reason = #{failureReason}, updated_at = NOW()
            WHERE id = #{id} AND request_id = #{requestId} AND binding_status = #{expectedStatus}
            """)
    int applyResult(@Param("id") Integer id,
                    @Param("requestId") String requestId,
                    @Param("expectedStatus") String expectedStatus,
                    @Param("targetStatus") String targetStatus,
                    @Param("failureReason") String failureReason);

    @Delete("""
            DELETE FROM devicetousers
            WHERE id = #{id} AND request_id = #{requestId} AND binding_status = 'PENDING_UNBIND'
            """)
    int completeUnbind(@Param("id") Integer id, @Param("requestId") String requestId);

}



