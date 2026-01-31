// generated from rosidl_generator_c/resource/idl__struct.h.em
// with input from bird_deterrent_vineyard_msgs:msg/Polygon2D.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__POLYGON2_D__STRUCT_H_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__POLYGON2_D__STRUCT_H_

#ifdef __cplusplus
extern "C"
{
#endif

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


// Constants defined in the message

// Include directives for member types
// Member 'points'
#include "bird_deterrent_vineyard_msgs/msg/detail/point2_d__struct.h"

/// Struct defined in msg/Polygon2D in the package bird_deterrent_vineyard_msgs.
typedef struct bird_deterrent_vineyard_msgs__msg__Polygon2D
{
  bird_deterrent_vineyard_msgs__msg__Point2D__Sequence points;
} bird_deterrent_vineyard_msgs__msg__Polygon2D;

// Struct for a sequence of bird_deterrent_vineyard_msgs__msg__Polygon2D.
typedef struct bird_deterrent_vineyard_msgs__msg__Polygon2D__Sequence
{
  bird_deterrent_vineyard_msgs__msg__Polygon2D * data;
  /// The number of valid items in data
  size_t size;
  /// The number of allocated items in data
  size_t capacity;
} bird_deterrent_vineyard_msgs__msg__Polygon2D__Sequence;

#ifdef __cplusplus
}
#endif

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__POLYGON2_D__STRUCT_H_
