//package com.schoolwork.epsys.common.config;
//
//import lombok.Data;
//import org.redisson.Redisson;
//import org.redisson.api.RedissonClient;
//import org.redisson.config.Config;
//import org.redisson.config.SingleServerConfig;
//import org.springframework.boot.context.properties.ConfigurationProperties;
//import org.springframework.context.annotation.Bean;
//import org.springframework.context.annotation.Configuration;
//import org.springframework.util.StringUtils;
//
///**
// * Redisson 客户端配置类
// * 1. 加载Redis连接配置
// * 2. 构建单节点模式的RedissonClient实例
// */
//@Data // Lombok注解，自动生成getter/setter
//@Configuration // 声明为Spring配置类
//@ConfigurationProperties("spring.redis") // 绑定配置文件中的spring.redis前缀属性
//public class RedissonConfig {
//
//    // Redis服务器地址
//    private String host="localhost";
//
//    // Redis集群地址（本配置未使用，保留字段）
//    private String addresses;
//
//    // Redis访问密码
//    private String password;
//
//    // Redis端口号
//    private String port="6379"; // 默认端口6379
//
//    // 超时时间（默认3秒）
//    private int timeout = 3000;
//    // 连接池大小（默认64）
//    private int connectionPoolSize = 64;
//    // 最小空闲连接数（默认10）
//    private int connectionMinimumIdleSize = 10;
//    // 心跳检测间隔（默认60秒）
//    private int pingConnectionInterval = 60000;
//    // Redis地址前缀
//    private static String ADDRESS_PREFIX = "redis://";
//
//    /**
//     * 创建单节点模式的Redisson客户端
//     * @return RedissonClient实例
//     */
//    @Bean
//    RedissonClient redissonSingle() {
//        Config config = new Config(); // 创建Redisson配置对象
//
//        // 校验host是否为空
//        if(StringUtils.isEmpty(host)) {
//            throw new RuntimeException("host is empty"); // 抛出运行时异常
//        }
//
//        // 配置单节点服务器参数
//        SingleServerConfig serverConfig = config.useSingleServer()
//                // 设置Redis地址（格式：redis://host:port）
//                .setAddress(ADDRESS_PREFIX + this.host + ":" + port)
//                // 设置操作超时时间
//                .setTimeout(this.timeout)
//                // 设置心跳检测间隔
//                .setPingConnectionInterval(pingConnectionInterval)
//                // 设置连接池大小
//                .setConnectionPoolSize(this.connectionPoolSize)
//                // 设置最小空闲连接数
//                .setConnectionMinimumIdleSize(this.connectionMinimumIdleSize);
//
//        // 如果配置了密码，设置认证密码
//        if(!StringUtils.isEmpty(this.password)) {
//            serverConfig.setPassword(this.password);
//        }
//
//        // 创建并返回Redisson客户端实例
//        return Redisson.create(config);
//    }
//}