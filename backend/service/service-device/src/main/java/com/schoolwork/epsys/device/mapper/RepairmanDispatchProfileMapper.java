package com.schoolwork.epsys.device.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.schoolwork.epsys.model.device.RepairmanDispatchProfile;
import org.apache.ibatis.annotations.Select;

import java.util.List;

public interface RepairmanDispatchProfileMapper extends BaseMapper<RepairmanDispatchProfile> {
    @Select("SELECT skill_code FROM repairman_dispatch_skill WHERE worker_id = #{workerId} ORDER BY skill_code")
    List<String> selectSkills(Integer workerId);
}
