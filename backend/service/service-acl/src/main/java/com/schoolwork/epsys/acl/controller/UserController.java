package com.schoolwork.epsys.acl.controller;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.schoolwork.epsys.acl.service.RolesService;
import com.schoolwork.epsys.acl.service.UserService;
import com.schoolwork.epsys.acl.service.UsertoroleService;
import com.schoolwork.epsys.common.Result;
import com.schoolwork.epsys.common.ResultCodeEnum;
import com.schoolwork.epsys.model.acl.Roles;
import com.schoolwork.epsys.model.acl.User;
import com.schoolwork.epsys.model.acl.Usertorole;
import com.schoolwork.epsys.model.approval.RepairmanApplication;
import io.jsonwebtoken.Claims;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.constraints.Pattern;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.io.IOException;
import java.util.*;
import java.util.concurrent.TimeUnit;

import com.schoolwork.epsys.utils.JwtUtils;
import com.schoolwork.epsys.utils.WebUtil;

/**
 * 用户账户接口，负责登录注册、身份信息查询、角色查询和维修员申请等业务。
 */
@Transactional
@RestController
@RequestMapping("/user")
public class UserController {
    @Autowired
    private UserService userService;

    @Autowired
    private UsertoroleService usertoroleService;

    @Autowired
    private RabbitTemplate rabbitTemplate;

    @Autowired
     private RedisTemplate redisTemplate;





    /**
     * 校验用户名和密码，登录成功后签发 JWT，并在 Redis 中记录在线用户。
     */
    @RequestMapping("/login")
    public void login(HttpServletRequest req, HttpServletResponse resp, @Pattern(regexp = "^\\S{3,16}$") String username,
                      @Pattern(regexp = "^\\S{5,16}$") String password) throws ServletException, IOException {

        User user = new User();
        user.setUsername(username);
        user.setPassword(password);
        QueryWrapper<User> queryWrapper = new QueryWrapper<>();
        queryWrapper.eq("username", username);
        queryWrapper.eq("password", password);
        User user1 = userService.getOne(queryWrapper);
        if (user1 != null && user1.getPassword().equals(password) && user1.getStatus() == 1) {
            String token = JwtUtils.setJwt(user1.getId(), user1.getUsername());
            System.out.println("这是生成的token：" + token);
            Map<String, Object> data = new HashMap<>();
            data.put("token", token);
            data.put("user", user1);

            // 使用Hash存储用户在线状态
            String onlineUsersKey = "online:users";  // Hash的key名称
            redisTemplate.opsForHash().put(
                    onlineUsersKey,
                    user1.getId().toString(),  // Hash的field，使用用户ID
                    user1      // Hash的value，存储用户对象
            );
            // 可以设置过期时间
            redisTemplate.expire(onlineUsersKey, 20, TimeUnit.MINUTES);

            Result result = Result.ok(data);
            WebUtil.writeJson(resp, result);
        } else {
            Result result = Result.build(null, ResultCodeEnum.USERNAEM_ERROR);
            WebUtil.writeJson(resp, result);
        }
    }

    /**
     * 注册普通用户，并在注册成功后为其分配默认角色。
     */
    @RequestMapping("/register")
    public void register(HttpServletRequest req, HttpServletResponse resp, @Pattern(regexp = "^\\S{3,16}$") String username,
                         @Pattern(regexp = "^\\S{5,16}$") String password, String phonenum) throws ServletException, IOException{

        User existUser=userService.getOne(new QueryWrapper<User>().eq("username", username));
        if(existUser!=null){
            Result result=Result.build(null,ResultCodeEnum.USERNAME_USED);
            WebUtil.writeJson(resp,result);
            return;
        }
        User user=new User();
        user.setUsername(username);
        user.setPassword(password);
        user.setPhone(phonenum);
        user.setCreateTime(new Date());
        user.setLastTime(new Date());
        Boolean flag=userService.save(user);
        if(flag){
            Usertorole usertorole=new Usertorole();
            usertorole.setUserId(user.getId());
            usertorole.setRoleId(2);
            usertoroleService.save(usertorole);
            Result result=Result.ok("注册成功");
            WebUtil.writeJson(resp,result);
        }else{
            Result result=Result.build(null,ResultCodeEnum.LAZY_ERROR);
            WebUtil.writeJson(resp,result);
        }
    }

    /**
     * 解析请求中的 JWT，查询并返回当前登录用户的资料。
     */
    @RequestMapping("/getUserInfo")
    public void getUserInfo(@RequestHeader(value = "Authorization", required = false) String authorization,
                            HttpServletRequest req, HttpServletResponse resp) throws ServletException, IOException {
        String token = authorization;
        Claims claims = JwtUtils.parseJwt(token);
        Integer id = claims.get("id", Integer.class);
//        QueryWrapper<User> queryWrapper = new QueryWrapper<>();
//        queryWrapper.eq("id",id);
        User user=userService.getById(id);
        System.out.println("这是获取到的用户信息："+user);
        System.out.println(user);
        Map data = new HashMap();
        data.put("user",user);
        Result result = Result.ok(data);
        WebUtil.writeJson(resp,result);
    }

    /**
     * 根据 JWT 中的用户 ID 查询当前用户拥有的全部角色 ID。
     */
    @RequestMapping("/getUserRole")
    public void getUserRole(@RequestHeader(value = "Authorization", required = false) String authorization,
                            HttpServletRequest req, HttpServletResponse resp) throws ServletException, IOException {
        String token = authorization;
        Claims claims = JwtUtils.parseJwt(token);
        Integer id = claims.get("id", Integer.class);
        QueryWrapper<Usertorole> queryWrapper = new QueryWrapper<>();
        queryWrapper.eq("user_id", id);
        List<Usertorole> usertoroleList = usertoroleService.list(queryWrapper);
        List<Integer> roleIds = new ArrayList<>();
        for (Usertorole usertorole : usertoroleList) {
            roleIds.add(usertorole.getRoleId());
        }
        Map data = new HashMap();
        data.put("roleIds", roleIds);
        Result result = Result.ok(data);
        WebUtil.writeJson(resp, result);
    }



    /**
     * 提交维修员申请，将申请消息发送到 RabbitMQ 交由审批服务异步处理。
     */
    @PostMapping("/apply")
    public void apply(HttpServletRequest req, HttpServletResponse resp,
                      @RequestHeader(value = "Authorization", required = false) String authorization,
                      @RequestBody RepairmanApplication repairmanApplication) {
        String token = authorization;
        Claims claims = JwtUtils.parseJwt(token);
        Integer id = claims.get("id", Integer.class);
        repairmanApplication.setUserId(id);
        System.out.println("这是repairmanApplication：" + repairmanApplication);
        rabbitTemplate.convertAndSend("repair_exchange", "repair_apply_queue", repairmanApplication);

        Result result = Result.ok("申请成功，请等待管理员审核");
        WebUtil.writeJson(resp, result);
    }

    /**
     * 根据 JWT 确定当前用户，并更新其个人资料。
     */
    @RequestMapping("/updateUserInfo")
    public void updateUserInfo(@RequestHeader(value = "Authorization", required = false) String authorization,@RequestBody User user,
                               HttpServletRequest req, HttpServletResponse resp) throws ServletException, IOException {
        String token = authorization;
        Claims claims = JwtUtils.parseJwt(token);
        Integer id = claims.get("id", Integer.class);
        user.setId(id);
        System.out.println("这是获取到的用户信息："+user);
        Boolean flag=userService.updateById(user);
        if(flag){
            Result result=Result.ok("修改成功");
            WebUtil.writeJson(resp,result);
        }else{
            Result result=Result.build(null,ResultCodeEnum.LAZY_ERROR);
            WebUtil.writeJson(resp,result);
        }
    }


}
