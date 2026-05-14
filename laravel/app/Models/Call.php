<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Str;

class Call extends Model
{
    protected $fillable = [
        'tenant_id',
        'user_id',
        'uuid',
        'filename',
        'original_name',
        'status',
        'duration_seconds',
        'transcription',
        'analysis',
        'score',
    ];

    protected $casts = [
        'analysis' => 'array',
    ];

    protected static function booted(): void
    {
        static::creating(function ($call) {
            $call->uuid = (string) Str::uuid();
        });
    }

    public function user()
    {
        return $this->belongsTo(User::class);
    }
}
