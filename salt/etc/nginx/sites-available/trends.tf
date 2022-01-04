# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

upstream netdata {
	server unix:/run/netdata/netdata.sock;
	keepalive 64;
}

map $http_upgrade $connection_upgrade {
	default upgrade;
	""      close;
}

{% set ssl %}
ssl_certificate         {{ certdir }}/fullchain.pem;
ssl_certificate_key     {{ certdir }}/privkey.pem;
ssl_trusted_certificate {{ certdir }}/chain.pem;
{% endset %}

{% set security %}
add_header X-Frame-Options           "SAMEORIGIN" always;
add_header X-XSS-Protection          "1; mode=block" always;
add_header X-Content-Type-Options    "nosniff" always;
add_header Referrer-Policy           "no-referrer-when-downgrade" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
{% endset %}

server {
	listen                  443 ssl http2;
	listen                  [::]:443 ssl http2;
	server_name             trends.tf;

	{{ ssl }}
	{{ security }}
	add_header Content-Security-Policy   "default-src 'self' http: https: data: blob: 'unsafe-inline'" always;
	
	location / {
		# default uwsgi_params
		include                       uwsgi_params;

		# uwsgi settings
		uwsgi_pass                    unix:{{ uwsgi_socket }};
		uwsgi_param Host              $host;
		uwsgi_param X-Real-IP         $remote_addr;
		uwsgi_param X-Forwarded-For   $proxy_add_x_forwarded_for;
		uwsgi_param X-Forwarded-Proto $http_x_forwarded_proto;

		# cache settings
		uwsgi_cache cache;
		uwsgi_cache_key $request_uri;
		uwsgi_cache_lock on;
		uwsgi_cache_use_stale updating;
		uwsgi_cache_valid 200 5m;
	}

	location ^~ /static/ {
		root       {{ site_packages }}/trends/site/;
		expires    365d;
		access_log off;
	}

	# favicon.ico
	location = /favicon.ico {
		access_log off;
		return 301 /static/img/favicon.ico;
	}

	# robots.txt
	location = /robots.txt {
		access_log off;
		return 301 /static/robots.txt;
	}
}

# munin metrics
server {
	listen                  443 ssl http2;
	listen                  [::]:443 ssl http2;
	server_name             netdata.trends.tf;

	{{ ssl }}
	ssl_client_certificate ca.crt;
	ssl_verify_client on;
	{{ security }}
	add_header Content-Security-Policy "default-src 'self' http: https: data: blob: 'unsafe-inline' 'unsafe-eval'" always;

	location / {
		include fastcgi_params;

		fastcgi_pass unix:/run/munin/fcgi-html.sock;
		fastcgi_param PATH_INFO $fastcgi_script_name;
	}

	location ^~ /graph/ {
		include fastcgi_params;

		fastcgi_split_path_info ^(/graph)(.*);
		fastcgi_param PATH_INFO $fastcgi_path_info;
		fastcgi_pass unix:/run/munin/fcgi-graph.sock;
	}

	location ^~ /static/ {
		root /etc/munin/;
		access_log off;
	}
}

# HTTP redirect
server {
	listen      80;
	listen      [::]:80;
	server_name .trends.tf;

	# ACME-challenge
	location ^~ /.well-known/acme-challenge/ {
		root /var/lib/letsencrypt/;
	}

	# Local stat collection
	location = /nginx_status {
		stub_status on;
		access_log off;
		allow 127.0.0.1;
		deny all;
	}

	location / {
		return 301 https://trends.tf$request_uri;
	}
}
