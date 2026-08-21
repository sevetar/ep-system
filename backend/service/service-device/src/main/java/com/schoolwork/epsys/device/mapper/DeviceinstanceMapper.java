package com.schoolwork.epsys.device.mapper;


import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.schoolwork.epsys.model.device.Deviceinstance;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

/**
* @author 27959
* @description 针对表【deviceinstance】的数据库操作Mapper
* @createDate 2025-04-07 08:24:12
* @Entity generator.domain.Deviceinstance
*/
public interface DeviceinstanceMapper extends BaseMapper<Deviceinstance> {

    @Update("""
            UPDATE deviceinstance
            SET status = #{targetStatus}
            WHERE id = #{deviceId} AND status = #{expectedStatus}
            """)
    int transitionStatus(@Param("deviceId") Integer deviceId,
                         @Param("expectedStatus") String expectedStatus,
                         @Param("targetStatus") String targetStatus);

}



