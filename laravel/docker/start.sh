#!/bin/sh

# Fix permissions AFTER volume mounts (build-time chown gets overwritten)
chown -R www-data:www-data storage bootstrap/cache
chmod -R 775 storage bootstrap/cache
mkdir -p storage/framework/views storage/framework/cache storage/framework/sessions
chown -R www-data:www-data storage/framework

php artisan config:cache
php artisan route:cache
php artisan migrate --force
php-fpm -D
nginx -g "daemon off;"
