// generated from rosidl_typesupport_introspection_cpp/resource/idl__type_support.cpp.em
// with input from bird_deterrent_vineyard_msgs:msg/Zones.idl
// generated code does not contain a copyright notice

#include "array"
#include "cstddef"
#include "string"
#include "vector"
#include "rosidl_runtime_c/message_type_support_struct.h"
#include "rosidl_typesupport_cpp/message_type_support.hpp"
#include "rosidl_typesupport_interface/macros.h"
#include "bird_deterrent_vineyard_msgs/msg/detail/zones__struct.hpp"
#include "rosidl_typesupport_introspection_cpp/field_types.hpp"
#include "rosidl_typesupport_introspection_cpp/identifier.hpp"
#include "rosidl_typesupport_introspection_cpp/message_introspection.hpp"
#include "rosidl_typesupport_introspection_cpp/message_type_support_decl.hpp"
#include "rosidl_typesupport_introspection_cpp/visibility_control.h"

namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

namespace rosidl_typesupport_introspection_cpp
{

void Zones_init_function(
  void * message_memory, rosidl_runtime_cpp::MessageInitialization _init)
{
  new (message_memory) bird_deterrent_vineyard_msgs::msg::Zones(_init);
}

void Zones_fini_function(void * message_memory)
{
  auto typed_message = static_cast<bird_deterrent_vineyard_msgs::msg::Zones *>(message_memory);
  typed_message->~Zones();
}

size_t size_function__Zones__zones(const void * untyped_member)
{
  const auto * member = reinterpret_cast<const std::vector<bird_deterrent_vineyard_msgs::msg::Zone> *>(untyped_member);
  return member->size();
}

const void * get_const_function__Zones__zones(const void * untyped_member, size_t index)
{
  const auto & member =
    *reinterpret_cast<const std::vector<bird_deterrent_vineyard_msgs::msg::Zone> *>(untyped_member);
  return &member[index];
}

void * get_function__Zones__zones(void * untyped_member, size_t index)
{
  auto & member =
    *reinterpret_cast<std::vector<bird_deterrent_vineyard_msgs::msg::Zone> *>(untyped_member);
  return &member[index];
}

void fetch_function__Zones__zones(
  const void * untyped_member, size_t index, void * untyped_value)
{
  const auto & item = *reinterpret_cast<const bird_deterrent_vineyard_msgs::msg::Zone *>(
    get_const_function__Zones__zones(untyped_member, index));
  auto & value = *reinterpret_cast<bird_deterrent_vineyard_msgs::msg::Zone *>(untyped_value);
  value = item;
}

void assign_function__Zones__zones(
  void * untyped_member, size_t index, const void * untyped_value)
{
  auto & item = *reinterpret_cast<bird_deterrent_vineyard_msgs::msg::Zone *>(
    get_function__Zones__zones(untyped_member, index));
  const auto & value = *reinterpret_cast<const bird_deterrent_vineyard_msgs::msg::Zone *>(untyped_value);
  item = value;
}

void resize_function__Zones__zones(void * untyped_member, size_t size)
{
  auto * member =
    reinterpret_cast<std::vector<bird_deterrent_vineyard_msgs::msg::Zone> *>(untyped_member);
  member->resize(size);
}

static const ::rosidl_typesupport_introspection_cpp::MessageMember Zones_message_member_array[2] = {
  {
    "t",  // name
    ::rosidl_typesupport_introspection_cpp::ROS_TYPE_DOUBLE,  // type
    0,  // upper bound of string
    nullptr,  // members of sub message
    false,  // is array
    0,  // array size
    false,  // is upper bound
    offsetof(bird_deterrent_vineyard_msgs::msg::Zones, t),  // bytes offset in struct
    nullptr,  // default value
    nullptr,  // size() function pointer
    nullptr,  // get_const(index) function pointer
    nullptr,  // get(index) function pointer
    nullptr,  // fetch(index, &value) function pointer
    nullptr,  // assign(index, value) function pointer
    nullptr  // resize(index) function pointer
  },
  {
    "zones",  // name
    ::rosidl_typesupport_introspection_cpp::ROS_TYPE_MESSAGE,  // type
    0,  // upper bound of string
    ::rosidl_typesupport_introspection_cpp::get_message_type_support_handle<bird_deterrent_vineyard_msgs::msg::Zone>(),  // members of sub message
    true,  // is array
    0,  // array size
    false,  // is upper bound
    offsetof(bird_deterrent_vineyard_msgs::msg::Zones, zones),  // bytes offset in struct
    nullptr,  // default value
    size_function__Zones__zones,  // size() function pointer
    get_const_function__Zones__zones,  // get_const(index) function pointer
    get_function__Zones__zones,  // get(index) function pointer
    fetch_function__Zones__zones,  // fetch(index, &value) function pointer
    assign_function__Zones__zones,  // assign(index, value) function pointer
    resize_function__Zones__zones  // resize(index) function pointer
  }
};

static const ::rosidl_typesupport_introspection_cpp::MessageMembers Zones_message_members = {
  "bird_deterrent_vineyard_msgs::msg",  // message namespace
  "Zones",  // message name
  2,  // number of fields
  sizeof(bird_deterrent_vineyard_msgs::msg::Zones),
  Zones_message_member_array,  // message members
  Zones_init_function,  // function to initialize message memory (memory has to be allocated)
  Zones_fini_function  // function to terminate message instance (will not free memory)
};

static const rosidl_message_type_support_t Zones_message_type_support_handle = {
  ::rosidl_typesupport_introspection_cpp::typesupport_identifier,
  &Zones_message_members,
  get_message_typesupport_handle_function,
};

}  // namespace rosidl_typesupport_introspection_cpp

}  // namespace msg

}  // namespace bird_deterrent_vineyard_msgs


namespace rosidl_typesupport_introspection_cpp
{

template<>
ROSIDL_TYPESUPPORT_INTROSPECTION_CPP_PUBLIC
const rosidl_message_type_support_t *
get_message_type_support_handle<bird_deterrent_vineyard_msgs::msg::Zones>()
{
  return &::bird_deterrent_vineyard_msgs::msg::rosidl_typesupport_introspection_cpp::Zones_message_type_support_handle;
}

}  // namespace rosidl_typesupport_introspection_cpp

#ifdef __cplusplus
extern "C"
{
#endif

ROSIDL_TYPESUPPORT_INTROSPECTION_CPP_PUBLIC
const rosidl_message_type_support_t *
ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(rosidl_typesupport_introspection_cpp, bird_deterrent_vineyard_msgs, msg, Zones)() {
  return &::bird_deterrent_vineyard_msgs::msg::rosidl_typesupport_introspection_cpp::Zones_message_type_support_handle;
}

#ifdef __cplusplus
}
#endif
