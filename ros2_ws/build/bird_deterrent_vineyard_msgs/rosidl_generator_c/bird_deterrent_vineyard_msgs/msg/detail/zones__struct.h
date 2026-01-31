// generated from rosidl_generator_c/resource/idl__struct.h.em
// with input from bird_deterrent_vineyard_msgs:msg/Zones.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONES__STRUCT_H_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONES__STRUCT_H_

#ifdef __cplusplus
extern "C"
{
#endif

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


// Constants defined in the message

// Include directives for member types
// Member 'zones'
#include "bird_deterrent_vineyard_msgs/msg/detail/zone__struct.h"

/// Struct defined in msg/Zones in the package bird_deterrent_vineyard_msgs.
typedef struct bird_deterrent_vineyard_msgs__msg__Zones
{
  double t;
  bird_deterrent_vineyard_msgs__msg__Zone__Sequence zones;
} bird_deterrent_vineyard_msgs__msg__Zones;

// Struct for a sequence of bird_deterrent_vineyard_msgs__msg__Zones.
typedef struct bird_deterrent_vineyard_msgs__msg__Zones__Sequence
{
  bird_deterrent_vineyard_msgs__msg__Zones * data;
  /// The number of valid items in data
  size_t size;
  /// The number of allocated items in data
  size_t capacity;
} bird_deterrent_vineyard_msgs__msg__Zones__Sequence;

#ifdef __cplusplus
}
#endif

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONES__STRUCT_H_
