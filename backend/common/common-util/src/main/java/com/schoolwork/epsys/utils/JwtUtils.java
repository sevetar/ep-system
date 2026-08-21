package com.schoolwork.epsys.utils;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.SignatureAlgorithm;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import java.util.Base64;
import java.util.Date;
import java.util.HashMap;
import java.util.Map;

@Component
public class JwtUtils {
    //json web token
    //设置密钥
    private static String signKey = "itcastismypassworddonttellitcastismypassworddonttellitcastismypl";
    //设置有效时间
    private static Long expire = System.currentTimeMillis()+1000*60*30;

    public static String setJwt(Integer id, String username){
        //生成jwt令牌
        //设置有效载荷
        Map<String,Object> map = new HashMap<>();
        map.put("id",id);
        map.put("username",username);
//        map.put("password",123456);

//生成jwt令牌
        String itcast = Jwts.builder().setClaims(map).
                signWith(SignatureAlgorithm.HS256, signKey).//设置秘钥
                        setExpiration(new Date(System.currentTimeMillis() + 3600 * 1000)).//设置有效时间
                        compact();

        System.out.println(itcast);
        return itcast;
//        String jwt = Jwts.builder().setClaims(claims).signWith(SignatureAlgorithm.HS256, signKey).setExpiration(new Date(expire)).compact();
//        return jwt;
    }

    //校验jwt
    public static Claims parseJwt(String jwt){
        Claims claims = Jwts.parser().setSigningKey(signKey).parseClaimsJws(jwt).getBody();
        return claims;
    }

}
