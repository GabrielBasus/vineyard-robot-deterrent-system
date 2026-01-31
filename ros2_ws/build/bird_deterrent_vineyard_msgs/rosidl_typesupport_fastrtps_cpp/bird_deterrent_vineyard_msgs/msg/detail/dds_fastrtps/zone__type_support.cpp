// generated from rosidl_typesupport_fastrtps_cpp/resource/idl__type_support.cpp.em
// with input from bird_deterrent_vineyard_msgs:msg/Zone.idl
// generated code does not contain a copyright notice
#include "bird_deterrent_vineyard_msgs/msg/detail/zone__rosidl_typesupport_fastrtps_cpp.hpp"
#include "bird_deterrent_vineyard_msgs/msg/detail/zone__struct.hpp"

#include <limits>
#include <stdexcept>
#include <string>
#include "rosidl_typesupport_cpp/message_type_support.hpp"
#include "rosidl_typesupport_fastrtps_cpp/identifier.hpp"
#include "rosidl_typesupport_fastrtps_cpp/message_type_support.h"
#include "rosidl_typesupport_fastrtps_cpp/message_type_support_decl.hpp"
#include "rosidl_typesupport_fastrtps_cpp/wstring_conversion.hpp"
#include "fastcdr/Cdr.h"


// forward declaration of message dependencies and their conversion functions
namespace bird_deterrent_vineyard_msgs
{
namespace msg
{
namespace typesupport_fastrtps_cpp
{
bool cdr_serialize(
  const bird_deterrent_vineyard_msgs::msg::Polygon2D &,
  eprosima::fastcdr::Cdr &);
bool cdr_deserialize(
  eprosima::fastcdr::Cdr &,
  bird_deterrent_vineyard_msgs::msg::Polygon2D &);
size_t get_serialized_size(
  const bird_deterrent_vineyard_msgs::msg::Polygon2D &,
  size_t current_alignment);
size_t
max_serialized_size_Polygon2D(
  bool & full_bounded,
  bool & is_plain,
  size_t current_alignment);
}  // namespace typesupport_fastrtps_cpp
}  // namespace msg
}  // namespace bird_deterrent_vineyard_msgs


namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

namespace typesupport_fastrtps_cpp
{

bool
ROSIDL_TYPESUPPORT_FASTRTPS_CPP_PUBLIC_bird_deterrent_vineyard_msgs
cdr_serialize(
  const bird_deterrent_vineyard_msgs::msg::Zone & ros_message,
  eprosima::fastcdr::Cdr & cdr)
{
  // Member: robot_id
  cdr << ros_message.robot_id;
  // Member: polygon
  bird_deterrent_vineyard_msgs::msg::typesupport_fastrtps_cpp::cdr_serialize(
    ros_message.polygon,
    cdr);
  // Member: neighbors
  {
    cdr << ros_message.neighbors;
  }
  return true;
}

bool
ROSIDL_TYPESUPPORT_FASTRTPS_CPP_PUBLIC_bird_deterrent_vineyard_msgs
cdr_deserialize(
  eprosima::fastcdr::Cdr & cdr,
  bird_deterrent_vineyard_msgs::msg::Zone & ros_message)
{
  // Member: robot_id
  cdr >> ros_message.robot_id;

  // Member: polygon
  bird_deterrent_vineyard_msgs::msg::typesupport_fastrtps_cpp::cdr_deserialize(
    cdr, ros_message.polygon);

  // Member: neighbors
  {
    cdr >> ros_message.neighbors;
  }

  return true;
}

size_t
ROSIDL_TYPESUPPORT_FASTRTPS_CPP_PUBLIC_bird_deterrent_vineyard_msgs
get_serialized_size(
  const bird_deterrent_vineyard_msgs::msg::Zone & ros_message,
  size_t current_alignment)
{
  size_t initial_alignment = current_alignment;

  const size_t padding = 4;
  const size_t wchar_size = 4;
  (void)padding;
  (void)wchar_size;

  // Member: robot_id
  current_alignment += padding +
    eprosima::fastcdr::Cdr::alignment(current_alignment, padding) +
    (ros_message.robot_id.size() + 1);
  // Member: polygon

  current_alignment +=
    bird_deterrent_vineyard_msgs::msg::typesupport_fastrtps_cpp::get_serialized_size(
    ros_message.polygon, current_alignment);
  // Member: neighbors
  {
    size_t array_size = ros_message.neighbors.size();

    current_alignment += padding +
      eprosima::fastcdr::Cdr::alignment(current_alignment, padding);
    for (size_t index = 0; index < array_size; ++index) {
      current_alignment += padding +
        eprosima::fastcdr::Cdr::alignment(current_alignment, padding) +
        (ros_message.neighbors[index].size() + 1);
    }
  }

  return current_alignment - initial_alignment;
}

size_t
ROSIDL_TYPESUPPORT_FASTRTPS_CPP_PUBLIC_bird_deterrent_vineyard_msgs
max_serialized_size_Zone(
  bool & full_bounded,
  bool & is_plain,
  size_t current_alignment)
{
  size_t initial_alignment = current_alignment;

  const size_t padding = 4;
  const size_t wchar_size = 4;
  size_t last_member_size = 0;
  (void)last_member_size;
  (void)padding;
  (void)wchar_size;

  full_bounded = true;
  is_plain = true;


  // Member: robot_id
  {
    size_t array_size = 1;

    full_bounded = false;
    is_plain = false;
    for (size_t index = 0; index < array_size; ++index) {
      current_alignment += padding +
        eprosima::fastcdr::Cdr::alignment(current_alignment, padding) +
        1;
    }
  }

  // Member: polygon
  {
    size_t array_size = 1;


    last_member_size = 0;
    for (size_t index = 0; index < array_size; ++index) {
      bool inner_full_bounded;
      bool inner_is_plain;
      size_t inner_size =
        bird_deterrent_vineyard_msgs::msg::typesupport_fastrtps_cpp::max_serialized_size_Polygon2D(
        inner_full_bounded, inner_is_plain, current_alignment);
      last_member_size += inner_size;
      current_alignment += inner_size;
      full_bounded &= inner_full_bounded;
      is_plain &= inner_is_plain;
    }
  }

  // Member: neighbors
  {
    size_t array_size = 0;
    full_bounded = false;
    is_plain = false;
    current_alignment += padding +
      eprosima::fastcdr::Cdr::alignment(current_alignment, padding);

    full_bounded = false;
    is_plain = false;
    for (size_t index = 0; index < array_size; ++index) {
      current_alignment += padding +
        eprosima::fastcdr::Cdr::alignment(current_alignment, padding) +
        1;
    }
  }

  size_t ret_val = current_alignment - initial_alignment;
  if (is_plain) {
    // All members are plain, and type is not empty.
    // We still need to check that the in-memory alignment
    // is the same as the CDR mandated alignment.
    using DataType = bird_deterrent_vineyard_msgs::msg::Zone;
    is_plain =
      (
      offsetof(DataType, neighbors) +
      last_member_size
      ) == ret_val;
  }

  return ret_val;
}

static bool _Zone__cdr_serialize(
  const void * untyped_ros_message,
  eprosima::fastcdr::Cdr & cdr)
{
  auto typed_message =
    static_cast<const bird_deterrent_vineyard_msgs::msg::Zone *>(
    untyped_ros_message);
  return cdr_serialize(*typed_message, cdr);
}

static bool _Zone__cdr_deserialize(
  eprosima::fastcdr::Cdr & cdr,
  void * untyped_ros_message)
{
  auto typed_message =
    static_cast<bird_deterrent_vineyard_msgs::msg::Zone *>(
    untyped_ros_message);
  return cdr_deserialize(cdr, *typed_message);
}

static uint32_t _Zone__get_serialized_size(
  const void * untyped_ros_message)
{
  auto typed_message =
    static_cast<const bird_deterrent_vineyard_msgs::msg::Zone *>(
    untyped_ros_message);
  return static_cast<uint32_t>(get_serialized_size(*typed_message, 0));
}

static size_t _Zone__max_serialized_size(char & bounds_info)
{
  bool full_bounded;
  bool is_plain;
  size_t ret_val;

  ret_val = max_serialized_size_Zone(full_bounded, is_plain, 0);

  bounds_info =
    is_plain ? ROSIDL_TYPESUPPORT_FASTRTPS_PLAIN_TYPE :
    full_bounded ? ROSIDL_TYPESUPPORT_FASTRTPS_BOUNDED_TYPE : ROSIDL_TYPESUPPORT_FASTRTPS_UNBOUNDED_TYPE;
  return ret_val;
}

static message_type_support_callbacks_t _Zone__callbacks = {
  "bird_deterrent_vineyard_msgs::msg",
  "Zone",
  _Zone__cdr_serialize,
  _Zone__cdr_deserialize,
  _Zone__get_serialized_size,
  _Zone__max_serialized_size
};

static rosidl_message_type_support_t _Zone__handle = {
  rosidl_typesupport_fastrtps_cpp::typesupport_identifier,
  &_Zone__callbacks,
  get_message_typesupport_handle_function,
};

}  // namespace typesupport_fastrtps_cpp

}  // namespace msg

}  // namespace bird_deterrent_vineyard_msgs

namespace rosidl_typesupport_fastrtps_cpp
{

template<>
ROSIDL_TYPESUPPORT_FASTRTPS_CPP_EXPORT_bird_deterrent_vineyard_msgs
const rosidl_message_type_support_t *
get_message_type_support_handle<bird_deterrent_vineyard_msgs::msg::Zone>()
{
  return &bird_deterrent_vineyard_msgs::msg::typesupport_fastrtps_cpp::_Zone__handle;
}

}  // namespace rosidl_typesupport_fastrtps_cpp

#ifdef __cplusplus
extern "C"
{
#endif

const rosidl_message_type_support_t *
ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(rosidl_typesupport_fastrtps_cpp, bird_deterrent_vineyard_msgs, msg, Zone)() {
  return &bird_deterrent_vineyard_msgs::msg::typesupport_fastrtps_cpp::_Zone__handle;
}

#ifdef __cplusplus
}
#endif
