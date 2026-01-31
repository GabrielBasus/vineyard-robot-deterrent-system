// generated from rosidl_typesupport_introspection_c/resource/idl__type_support.c.em
// with input from bird_deterrent_vineyard_msgs:msg/Zones.idl
// generated code does not contain a copyright notice

#include <stddef.h>
#include "bird_deterrent_vineyard_msgs/msg/detail/zones__rosidl_typesupport_introspection_c.h"
#include "bird_deterrent_vineyard_msgs/msg/rosidl_typesupport_introspection_c__visibility_control.h"
#include "rosidl_typesupport_introspection_c/field_types.h"
#include "rosidl_typesupport_introspection_c/identifier.h"
#include "rosidl_typesupport_introspection_c/message_introspection.h"
#include "bird_deterrent_vineyard_msgs/msg/detail/zones__functions.h"
#include "bird_deterrent_vineyard_msgs/msg/detail/zones__struct.h"


// Include directives for member types
// Member `zones`
#include "bird_deterrent_vineyard_msgs/msg/zone.h"
// Member `zones`
#include "bird_deterrent_vineyard_msgs/msg/detail/zone__rosidl_typesupport_introspection_c.h"

#ifdef __cplusplus
extern "C"
{
#endif

void bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__Zones_init_function(
  void * message_memory, enum rosidl_runtime_c__message_initialization _init)
{
  // TODO(karsten1987): initializers are not yet implemented for typesupport c
  // see https://github.com/ros2/ros2/issues/397
  (void) _init;
  bird_deterrent_vineyard_msgs__msg__Zones__init(message_memory);
}

void bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__Zones_fini_function(void * message_memory)
{
  bird_deterrent_vineyard_msgs__msg__Zones__fini(message_memory);
}

size_t bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__size_function__Zones__zones(
  const void * untyped_member)
{
  const bird_deterrent_vineyard_msgs__msg__Zone__Sequence * member =
    (const bird_deterrent_vineyard_msgs__msg__Zone__Sequence *)(untyped_member);
  return member->size;
}

const void * bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__get_const_function__Zones__zones(
  const void * untyped_member, size_t index)
{
  const bird_deterrent_vineyard_msgs__msg__Zone__Sequence * member =
    (const bird_deterrent_vineyard_msgs__msg__Zone__Sequence *)(untyped_member);
  return &member->data[index];
}

void * bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__get_function__Zones__zones(
  void * untyped_member, size_t index)
{
  bird_deterrent_vineyard_msgs__msg__Zone__Sequence * member =
    (bird_deterrent_vineyard_msgs__msg__Zone__Sequence *)(untyped_member);
  return &member->data[index];
}

void bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__fetch_function__Zones__zones(
  const void * untyped_member, size_t index, void * untyped_value)
{
  const bird_deterrent_vineyard_msgs__msg__Zone * item =
    ((const bird_deterrent_vineyard_msgs__msg__Zone *)
    bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__get_const_function__Zones__zones(untyped_member, index));
  bird_deterrent_vineyard_msgs__msg__Zone * value =
    (bird_deterrent_vineyard_msgs__msg__Zone *)(untyped_value);
  *value = *item;
}

void bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__assign_function__Zones__zones(
  void * untyped_member, size_t index, const void * untyped_value)
{
  bird_deterrent_vineyard_msgs__msg__Zone * item =
    ((bird_deterrent_vineyard_msgs__msg__Zone *)
    bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__get_function__Zones__zones(untyped_member, index));
  const bird_deterrent_vineyard_msgs__msg__Zone * value =
    (const bird_deterrent_vineyard_msgs__msg__Zone *)(untyped_value);
  *item = *value;
}

bool bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__resize_function__Zones__zones(
  void * untyped_member, size_t size)
{
  bird_deterrent_vineyard_msgs__msg__Zone__Sequence * member =
    (bird_deterrent_vineyard_msgs__msg__Zone__Sequence *)(untyped_member);
  bird_deterrent_vineyard_msgs__msg__Zone__Sequence__fini(member);
  return bird_deterrent_vineyard_msgs__msg__Zone__Sequence__init(member, size);
}

static rosidl_typesupport_introspection_c__MessageMember bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__Zones_message_member_array[2] = {
  {
    "t",  // name
    rosidl_typesupport_introspection_c__ROS_TYPE_DOUBLE,  // type
    0,  // upper bound of string
    NULL,  // members of sub message
    false,  // is array
    0,  // array size
    false,  // is upper bound
    offsetof(bird_deterrent_vineyard_msgs__msg__Zones, t),  // bytes offset in struct
    NULL,  // default value
    NULL,  // size() function pointer
    NULL,  // get_const(index) function pointer
    NULL,  // get(index) function pointer
    NULL,  // fetch(index, &value) function pointer
    NULL,  // assign(index, value) function pointer
    NULL  // resize(index) function pointer
  },
  {
    "zones",  // name
    rosidl_typesupport_introspection_c__ROS_TYPE_MESSAGE,  // type
    0,  // upper bound of string
    NULL,  // members of sub message (initialized later)
    true,  // is array
    0,  // array size
    false,  // is upper bound
    offsetof(bird_deterrent_vineyard_msgs__msg__Zones, zones),  // bytes offset in struct
    NULL,  // default value
    bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__size_function__Zones__zones,  // size() function pointer
    bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__get_const_function__Zones__zones,  // get_const(index) function pointer
    bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__get_function__Zones__zones,  // get(index) function pointer
    bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__fetch_function__Zones__zones,  // fetch(index, &value) function pointer
    bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__assign_function__Zones__zones,  // assign(index, value) function pointer
    bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__resize_function__Zones__zones  // resize(index) function pointer
  }
};

static const rosidl_typesupport_introspection_c__MessageMembers bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__Zones_message_members = {
  "bird_deterrent_vineyard_msgs__msg",  // message namespace
  "Zones",  // message name
  2,  // number of fields
  sizeof(bird_deterrent_vineyard_msgs__msg__Zones),
  bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__Zones_message_member_array,  // message members
  bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__Zones_init_function,  // function to initialize message memory (memory has to be allocated)
  bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__Zones_fini_function  // function to terminate message instance (will not free memory)
};

// this is not const since it must be initialized on first access
// since C does not allow non-integral compile-time constants
static rosidl_message_type_support_t bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__Zones_message_type_support_handle = {
  0,
  &bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__Zones_message_members,
  get_message_typesupport_handle_function,
};

ROSIDL_TYPESUPPORT_INTROSPECTION_C_EXPORT_bird_deterrent_vineyard_msgs
const rosidl_message_type_support_t *
ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(rosidl_typesupport_introspection_c, bird_deterrent_vineyard_msgs, msg, Zones)() {
  bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__Zones_message_member_array[1].members_ =
    ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(rosidl_typesupport_introspection_c, bird_deterrent_vineyard_msgs, msg, Zone)();
  if (!bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__Zones_message_type_support_handle.typesupport_identifier) {
    bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__Zones_message_type_support_handle.typesupport_identifier =
      rosidl_typesupport_introspection_c__identifier;
  }
  return &bird_deterrent_vineyard_msgs__msg__Zones__rosidl_typesupport_introspection_c__Zones_message_type_support_handle;
}
#ifdef __cplusplus
}
#endif
