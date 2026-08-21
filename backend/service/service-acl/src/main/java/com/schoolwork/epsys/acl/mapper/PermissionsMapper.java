package com.schoolwork.epsys.acl.mapper;


import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.schoolwork.epsys.model.acl.Permissions;
import org.apache.ibatis.annotations.Param;

/**
* @description 针对表【permissions】的数据库操作Mapper
*/
public interface PermissionsMapper extends BaseMapper<Permissions> {
    boolean hasPermission(@Param("userId") int userId, @Param("permissionId") int permissionId);
}
