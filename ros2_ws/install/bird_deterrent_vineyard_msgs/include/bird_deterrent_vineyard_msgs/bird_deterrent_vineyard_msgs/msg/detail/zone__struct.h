// generated from rosidl_generator_c/resource/idl__struct.h.em
// with input from bird_deterrent_vineyard_msgs:msg/Zone.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONE__STRUCT_H_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONE__STRUCT_H_

#ifdef __cplusplus
extern "C"
{
#endif

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


// Constants defined in the message

// Include directives for member types
// Member 'robot_id'
// Member 'neighbors'
#include "rosidl_runtime_c/string.h"
// Member 'polygon'
#include "bird_deterrent_vineyard_msgs/msg/detail/polygon2_d__struct.h"

/// Struct defined in msg/Zone in the package bird_deterrent_vineyard_msgs.
typedef struct bird_deterrent_vineyard_msgs__msg__Zone
{
  rosidl_runtime_c__String robot_id;
  bird_deterrent_vineyard_msgs__msg__Polygon2D polygon;
  rosidl_runtime_c__String__Sequence neighbors;
} bird_deterrent_vineyard_msgs__msg__Zone;

// Struct for a sequence of bird_deterrent_vineyard_msgs__msg__Zone.
typedef struct bird_deterrent_vineyard_msgs__msg__Zone__Sequence
{
  bird_deterrent_vineyard_msgs__msg__Zone * data;
  /// The number of valid items in data
  size_t size;
  /// The number of allocated items in data
  size_t capacity;
} bird_deterrent_vineyard_msgs__msg__Zone__Sequence;

#ifdef __cplusplus
}
#endif

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONE__STRUCT_H_
