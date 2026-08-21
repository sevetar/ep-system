package com.schoolwork.epsys.acl.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.schoolwork.epsys.acl.mapper.UserMapper;
import com.schoolwork.epsys.acl.service.UserService;

import com.schoolwork.epsys.model.acl.User;
import org.springframework.stereotype.Service;

/**
* @author 27959
* @description 针对表【user】的数据库操作Service实现
* @createDate 2025-04-01 11:26:55
*/
@Service
public class UserServiceImpl extends ServiceImpl<UserMapper, User>
    implements UserService {

}




