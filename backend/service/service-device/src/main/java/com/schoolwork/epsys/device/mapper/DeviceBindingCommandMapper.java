package com.schoolwork.epsys.device.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.schoolwork.epsys.model.device.DeviceBindingCommand;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

public interface DeviceBindingCommandMapper extends BaseMapper<DeviceBindingCommand> {

    @Select("SELECT * FROM device_binding_command WHERE request_id = #{requestId} LIMIT 1")
    DeviceBindingCommand findByRequestId(@Param("requestId") String requestId);
}
